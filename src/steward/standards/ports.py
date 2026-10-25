from datetime import datetime
from typing import Protocol

from steward.github.models import RepoRef, TrackingIssue
from steward.standards.snapshot import RepoSnapshot


class StandardsGitHub(Protocol):
    async def snapshot(self, repo: RepoRef, since: datetime) -> RepoSnapshot | None: ...
    async def standards_issues(
        self, repo: RepoRef, creator: str, label: str
    ) -> list[TrackingIssue]: ...
    async def create_issue(self, repo: RepoRef, title: str, body: str, label: str) -> None: ...
    async def update_issue(self, repo: RepoRef, number: int, body: str, state: str) -> None: ...
