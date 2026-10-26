import asyncio
import json
import time
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from urllib.parse import urlparse

from workers import DurableObject, Response

from steward.config import MissingConfig, load_config
from steward.github.api import GitHubApi
from steward.github.app_auth import InstallationTokens, bot_login
from steward.github.client import GitHubClient
from steward.github.http import GitHubError
from steward.github.models import RepoRef
from steward.github.standards_client import StandardsClient
from steward.standards.service import StandardsService
from steward.worker.fetch_http import WorkersFetch
from steward.worker.responses import error_response, json_response
from steward.worker.webcrypto import WebCryptoSigner


class StandardsAudit(DurableObject):
    """Audits one repository per call: every audit gets its own budget of 50 subrequests.
    One instance per repository, so its audits run one at a time."""

    def __init__(self, ctx: Any, env: Any) -> None:
        super().__init__(ctx, env)
        self._lock = asyncio.Lock()
        self._http = WorkersFetch()
        self._tokens: InstallationTokens | None = None
        self._own_login: str | None = None

    async def fetch(self, request: Any) -> Response:
        if urlparse(request.url).path != "/audit" or request.method != "POST":
            return error_response("not_found", HTTPStatus.NOT_FOUND)
        try:
            config = load_config(self.env)
        except MissingConfig as error:
            print(f"configuration error: {error}")
            return error_response("misconfigured", HTTPStatus.INTERNAL_SERVER_ERROR)
        job = json.loads(await request.text())
        repo = RepoRef(job["owner"], job["name"])
        # Callers only audit the owner's repositories; nothing else is judged by its rules.
        if not config.accounts.is_owner(repo.owner):
            print(f"{repo.full_name}: not the owner's account")
            return error_response("forbidden", HTTPStatus.FORBIDDEN)
        signer = WebCryptoSigner(config.private_key_pkcs8)
        if self._tokens is None:
            self._tokens = InstallationTokens(self._http, config.app_id, signer, time.time)
        try:
            # The object uses no storage, so its input gate stays open while an audit awaits
            # GitHub: without the lock, two overlapping audits could both open an issue.
            async with self._lock:
                if self._own_login is None:
                    self._own_login = await bot_login(
                        self._http, config.app_id, signer, int(time.time())
                    )
                api = GitHubApi(self._http, self._tokens, job["installation_id"])
                service = StandardsService(
                    StandardsClient(api, GitHubClient(api)),
                    config.owner_email,
                    self._own_login,
                    lambda: datetime.now(UTC),
                )
                findings = await service.audit(repo)
        except GitHubError as error:
            print(f"{repo.full_name}: {error}")
            return error_response("github_error", HTTPStatus.BAD_GATEWAY)
        print(f"{repo.full_name}: {len(findings)} standards finding(s)")
        return json_response({"findings": len(findings)}, HTTPStatus.OK)
