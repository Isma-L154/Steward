import asyncio
import json
import time
from http import HTTPStatus
from typing import Any
from urllib.parse import urlparse

from workers import DurableObject, Response

from steward.config import MissingConfig, load_config
from steward.dependabot.service import DependabotService
from steward.github.api import GitHubApi
from steward.github.app_auth import InstallationTokens, bot_login
from steward.github.client import GitHubClient
from steward.github.http import GitHubError
from steward.github.models import RepoRef
from steward.worker.branch_update_memory import DurableObjectBranchUpdateMemory
from steward.worker.fetch_http import WorkersFetch
from steward.worker.responses import error_response, json_response
from steward.worker.webcrypto import WebCryptoSigner


class MergeQueue(DurableObject):
    """One instance per repository: evaluations run one at a time, so two Dependabot updates
    can never be merged onto the same `main` without CI running between them."""

    def __init__(self, ctx: Any, env: Any) -> None:
        super().__init__(ctx, env)
        self._lock = asyncio.Lock()
        self._http = WorkersFetch()
        self._tokens: InstallationTokens | None = None
        self._own_login: str | None = None

    async def fetch(self, request: Any) -> Response:
        if urlparse(request.url).path != "/evaluate" or request.method != "POST":
            return error_response("not_found", HTTPStatus.NOT_FOUND)
        try:
            config = load_config(self.env)
        except MissingConfig as error:
            print(f"configuration error: {error}")
            return error_response("misconfigured", HTTPStatus.INTERNAL_SERVER_ERROR)
        job = json.loads(await request.text())
        repo = RepoRef(job["owner"], job["name"])
        signer = WebCryptoSigner(config.private_key_pkcs8)
        if self._tokens is None:
            self._tokens = InstallationTokens(self._http, config.app_id, signer, time.time)
        try:
            async with self._lock:
                if self._own_login is None:
                    self._own_login = await bot_login(
                        self._http, config.app_id, signer, int(time.time())
                    )
                service = DependabotService(
                    GitHubClient(GitHubApi(self._http, self._tokens, job["installation_id"])),
                    DurableObjectBranchUpdateMemory(self.ctx.storage),
                    asyncio.sleep,
                    self._own_login,
                )
                decision = await service.evaluate(repo, job["number"])
        except GitHubError as error:
            print(f"{repo.full_name}#{job['number']}: {error}")
            return error_response("github_error", HTTPStatus.BAD_GATEWAY)
        print(f"{repo.full_name}#{job['number']}: {decision.kind} {decision.label or ''}")
        return json_response({"decision": decision.kind.value}, HTTPStatus.OK)
