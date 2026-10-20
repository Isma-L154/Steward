import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from steward.github.http import GitHubError
from steward.github.models import RepoRef
from steward.hub.snapshot import HubRepo


@dataclass
class FakeHubStore:
    values: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.values.get(key)

    async def put(self, key: str, value: dict[str, Any]) -> None:
        self.values[key] = value


@dataclass
class CountingSource:
    """Answers with one repository; can be held on an event or made to fail."""

    calls: int = 0
    fail: bool = False
    gate: asyncio.Event | None = None

    async def __call__(self) -> list[HubRepo]:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise GitHubError(502, "/graphql")
        return [HubRepo(RepoRef("o", "a"), ci_state="SUCCESS")]


@dataclass
class Clock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now
