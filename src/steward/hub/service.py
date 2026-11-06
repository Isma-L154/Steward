import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from steward.hub.health import health
from steward.hub.ports import HubStore
from steward.hub.report import report
from steward.hub.snapshot import HubRepo
from steward.hub.text import iso

SNAPSHOT_TTL = timedelta(minutes=5)
# Stored values outlive deploys. Bump this whenever health.py or report.py changes its output,
# so a value in the old shape is rebuilt instead of served.
SCHEMA_VERSION = 1
_HEALTH = "health"
_REPORT = "report"


class HubService:
    """Serves health and the report from one 5-minute snapshot. One lock covers
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
        return await self._snapshot(_HEALTH)

    async def report(self) -> dict[str, Any]:
        return await self._snapshot(_REPORT)

    async def _snapshot(self, key: str) -> dict[str, Any]:
        async with self._lock:
            cached = await self._current(key)
            if cached is not None and self._is_fresh(cached.get("fetched_at")):
                body: dict[str, Any] = cached["body"]
                return body
            repos = await self._source()
            now = self._clock()
            bodies = {
                _HEALTH: health(repos, now, self._app_login),
                _REPORT: report(repos, now, self._app_login),
            }
            for cache_key, body in bodies.items():
                await self._store.put(
                    cache_key, {"schema": SCHEMA_VERSION, "fetched_at": iso(now), "body": body}
                )
            return bodies[key]

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
        return timedelta(0) <= age < SNAPSHOT_TTL
