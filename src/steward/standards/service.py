from collections.abc import Callable
from datetime import datetime, timedelta

from steward.github.models import DEPENDABOT_LOGIN, RepoRef, graphql_login
from steward.standards.ports import StandardsGitHub
from steward.standards.report import ISSUE_LABEL, ISSUE_TITLE, render_body
from steward.standards.rules import run_checks
from steward.standards.snapshot import WINDOW_DAYS, Finding

_DEPENDABOT = frozenset({DEPENDABOT_LOGIN, graphql_login(DEPENDABOT_LOGIN)})


def _normalized(body: str) -> str:
    return body.replace("\r\n", "\n").strip()


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
        self._trusted_bots = _DEPENDABOT | {own_login, graphql_login(own_login)}

    async def audit(self, repo: RepoRef) -> list[Finding]:
        since = self._clock() - timedelta(days=WINDOW_DAYS)
        snapshot = await self._github.snapshot(repo, since)
        if snapshot is None:
            return []
        findings = run_checks(snapshot, self._owner_email, self._trusted_bots)
        body = render_body(repo, findings)
        issue = await self._github.tracking_issue(repo, self._own_login)
        if findings and issue is None:
            await self._github.create_issue(repo, ISSUE_TITLE, body, ISSUE_LABEL)
        elif findings and issue is not None:
            if issue.state != "open" or _normalized(issue.body) != _normalized(body):
                await self._github.update_issue(repo, issue.number, body, "open")
        elif issue is not None and issue.state == "open":
            await self._github.update_issue(repo, issue.number, body, "closed")
        return findings
