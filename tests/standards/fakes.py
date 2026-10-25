from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from steward.github.models import RepoRef, TrackingIssue
from steward.standards.snapshot import RepoSnapshot


@dataclass
class FakeStandardsGitHub:
    repo_snapshot: RepoSnapshot | None
    issues: list[TrackingIssue] = field(default_factory=list)
    writes: list[tuple[Any, ...]] = field(default_factory=list)
    asked_since: datetime | None = None

    async def snapshot(self, repo: RepoRef, since: datetime) -> RepoSnapshot | None:
        self.asked_since = since
        return self.repo_snapshot

    async def standards_issues(
        self, repo: RepoRef, creator: str, label: str
    ) -> list[TrackingIssue]:
        assert creator == "app-steward[bot]"
        assert label == "standards"
        return self.issues

    async def create_issue(self, repo: RepoRef, title: str, body: str, label: str) -> None:
        self.writes.append(("create", title, body, label))

    async def update_issue(self, repo: RepoRef, number: int, body: str, state: str) -> None:
        self.writes.append(("update", number, body, state))
