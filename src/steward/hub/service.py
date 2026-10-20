import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from steward.hub.health import health
from steward.hub.ports import HubStore
from steward.hub.report import report
from steward.hub.snapshot import HubRepo
from steward.hub.text import iso

HEALTH_TTL = timedelta(minutes=5)
# Stored values outlive deploys. Bump this whenever health.py or report.py changes its output,
# so a value in the old shape is rebuilt instead of served.
SCHEMA_VERSION = 1
_HEALTH = "health"
_REPORT = "report"


class HubService:
    """Serves health from a 5-minute cache and the stored weekly report. One lock covers
    every read-then-refresh, so callers arriving during a refresh wait for it instead of
    spending the installation's GitHub budget again."""

    def __init__(
        self,
        source: Callable[[], Awaitable[Sequence[HubRepo]]],
        store: HubStore,
        clock: Callable[[], datetime],
        app_login: str,
    ) -> None:
        self._source = source
        self._store = store
        self._clock = clock
        self._app_login = app_login
        self._lock = asyncio.Lock()

    async def health(self) -> dict[str, Any]:
        async with self._lock:
            cached = await self._current(_HEALTH)
            if cached is not None and self._is_fresh(cached.get("fetched_at")):
                body: dict[str, Any] = cached["body"]
                return body
            return await self._store_health(await self._source())

    async def report(self) -> dict[str, Any]:
        async with self._lock:
            stored = await self._current(_REPORT)
            if stored is not None:
                body: dict[str, Any] = stored["body"]
                return body
            return await self._build_report()

    async def build_report(self) -> dict[str, Any]:
        async with self._lock:
            return await self._build_report()

    async def _build_report(self) -> dict[str, Any]:
        # Read GitHub before touching storage: a failure leaves the previous report as it was.
        repos = await self._source()
        body = report(repos, self._clock(), self._app_login)
        await self._store.put(_REPORT, {"schema": SCHEMA_VERSION, "body": body})
        await self._store_health(repos)
        return body

    async def _store_health(self, repos: Sequence[HubRepo]) -> dict[str, Any]:
        now = self._clock()
        body = health(repos, now, self._app_login)
        await self._store.put(
            _HEALTH, {"schema": SCHEMA_VERSION, "fetched_at": iso(now), "body": body}
        )
        return body

    async def _current(self, key: str) -> dict[str, Any] | None:
        stored = await self._store.get(key)
        return stored if stored is not None and stored.get("schema") == SCHEMA_VERSION else None

    def _is_fresh(self, fetched_at: object) -> bool:
        if not isinstance(fetched_at, str):
            return False
        try:
            age = self._clock() - datetime.fromisoformat(fetched_at)
        except ValueError:
            return False
        # A stamp from the future (a clock jump) must not keep a cache alive indefinitely.
        return timedelta(0) <= age < HEALTH_TTL
