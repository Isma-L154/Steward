import asyncio
import json
import time
from http import HTTPStatus
from typing import Any
from urllib.parse import urlparse

from workers import DurableObject, Response

from steward.config import MissingConfig, load_config
from steward.dependabot.service import DependabotService
from steward.github.app_auth import InstallationTokens
from steward.github.client import GitHubClient
from steward.github.http import GitHubError
from steward.github.models import RepoRef
from steward.worker.fetch_http import WorkersFetch
from steward.worker.rebase_memory import DurableObjectRebaseMemory
from steward.worker.responses import error_response, json_response


class MergeQueue(DurableObject):
    """One instance per repository: evaluations run one at a time, so two Dependabot updates
    can never be merged onto the same `main` without CI running between them."""

    def __init__(self, ctx: Any, env: Any) -> None:
        super().__init__(ctx, env)
        self._lock = asyncio.Lock()
        self._http = WorkersFetch()
        self._tokens: InstallationTokens | None = None

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
        if self._tokens is None:
            self._tokens = InstallationTokens(
                self._http, config.app_id, config.private_key, time.time
            )
        github = GitHubClient(self._http, self._tokens, job["installation_id"])
        service = DependabotService(
            github, DurableObjectRebaseMemory(self.ctx.storage), asyncio.sleep
        )
        try:
            async with self._lock:
                decision = await service.evaluate(repo, job["number"])
        except GitHubError as error:
            print(f"{repo.full_name}#{job['number']}: {error}")
            return error_response("github_error", HTTPStatus.BAD_GATEWAY)
        print(f"{repo.full_name}#{job['number']}: {decision.kind} {decision.label or ''}")
        return json_response({"decision": decision.kind.value}, HTTPStatus.OK)
