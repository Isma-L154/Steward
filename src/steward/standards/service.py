from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from steward.github.models import RepoRef, TrackingIssue
from steward.standards.ports import StandardsGitHub
from steward.standards.report import ISSUE_LABEL, ISSUE_TITLE, listed_findings, render_body
from steward.standards.rules import run_checks
from steward.standards.snapshot import WINDOW_DAYS, Finding


def _normalized(body: str) -> str:
    return body.replace("\r\n", "\n").strip()


def _tracked(issues: Sequence[TrackingIssue]) -> TrackingIssue | None:
    """The open issue, else the newest one if Steward closed it; never one the owner closed."""
    for issue in issues:
        if issue.state == "open":
            return issue
    if issues and not listed_findings(issues[0].body):
        return issues[0]
    return None


class StandardsService:
    def __init__(
        self,
        github: StandardsGitHub,
        owner_email: str,
        own_login: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._github = github
        self._owner_email = owner_email
        self._own_login = own_login
        self._clock = clock

    async def audit(self, repo: RepoRef) -> list[Finding]:
        since = self._clock() - timedelta(days=WINDOW_DAYS)
        snapshot = await self._github.snapshot(repo, since)
        if snapshot is None:
            return []
        issues = await self._github.standards_issues(repo, self._own_login, ISSUE_LABEL)
        # Steward closes its issue with a body that lists nothing, so a closed issue that
        # still lists findings was closed by the owner: those findings are dismissed.
        dismissed = frozenset[str]().union(
            *(listed_findings(issue.body) for issue in issues if issue.state == "closed")
        )
        findings = [
            finding
            for finding in run_checks(snapshot, self._owner_email)
            if finding.detail not in dismissed
        ]
        body = render_body(repo, findings)
        issue = _tracked(issues)
        if findings and issue is None:
            await self._github.create_issue(repo, ISSUE_TITLE, body, ISSUE_LABEL)
        elif findings and issue is not None:
            if issue.state != "open" or _normalized(issue.body) != _normalized(body):
                await self._github.update_issue(repo, issue.number, body, "open")
        elif issue is not None and issue.state == "open":
            await self._github.update_issue(repo, issue.number, body, "closed")
        return findings
