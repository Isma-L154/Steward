import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from urllib.parse import urlparse

from workers import DurableObject, Response

from steward.config import Config, MissingConfig, load_config
from steward.github.api import GitHubApi
from steward.github.app_auth import bot_login, installations
from steward.github.http import GitHubError
from steward.github.hub_client import HubClient, account_repos, read_only_tokens
from steward.github.models import graphql_login
from steward.hub.service import HubService
from steward.hub.snapshot import HubRepo
from steward.standards.report import ISSUE_LABEL
from steward.worker.fetch_http import WorkersFetch
from steward.worker.responses import error_response, json_response
from steward.worker.webcrypto import WebCryptoSigner

_ROUTES: dict[tuple[str, str], Callable[[HubService], Awaitable[dict[str, Any]]]] = {
    ("GET", "/health"): HubService.health,
    ("GET", "/report"): HubService.report,
    ("POST", "/build-report"): HubService.build_report,
}


class DurableObjectHubStore:
    def __init__(self, storage: Any) -> None:
        self._storage = storage

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self._storage.get(key)
        return None if raw is None else dict(json.loads(raw))

    async def put(self, key: str, value: dict[str, Any]) -> None:
        await self._storage.put(key, json.dumps(value))


class HubData(DurableObject):
    """The single object behind the hub API: its health cache, its stored weekly report and
    the lock that keeps concurrent callers to one GitHub refresh."""

    def __init__(self, ctx: Any, env: Any) -> None:
        super().__init__(ctx, env)
        self._http = WorkersFetch()
        self._service: HubService | None = None
        self._setup = asyncio.Lock()

    async def fetch(self, request: Any) -> Response:
        handler = _ROUTES.get((request.method, urlparse(request.url).path))
        if handler is None:
            return error_response("not_found", HTTPStatus.NOT_FOUND)
        try:
            config = load_config(self.env)
        except MissingConfig as error:
            print(f"configuration error: {error}")
            return error_response("misconfigured", HTTPStatus.INTERNAL_SERVER_ERROR)
        try:
            body = await handler(await self._hub(config))
        except GitHubError as error:
            print(f"hub: {error}")
            return error_response("github_unavailable", HTTPStatus.BAD_GATEWAY)
        return json_response(body, HTTPStatus.OK)

    async def _hub(self, config: Config) -> HubService:
        async with self._setup:
            if self._service is None:
                signer = WebCryptoSigner(config.private_key_pkcs8)
                tokens = read_only_tokens(self._http, config.app_id, signer, time.time)
                login = await bot_login(self._http, config.app_id, signer, int(time.time()))

                async def source() -> list[HubRepo]:
                    installed = await installations(
                        self._http, config.app_id, signer, int(time.time())
                    )
                    ids = [installation.id for installation in installed]
                    return await account_repos(
                        ids,
                        lambda installation: HubClient(
                            GitHubApi(self._http, tokens, installation), ISSUE_LABEL
                        ),
                    )

                self._service = HubService(
                    source,
                    DurableObjectHubStore(self.ctx.storage),
                    lambda: datetime.now(UTC),
                    graphql_login(login),
                )
            return self._service
