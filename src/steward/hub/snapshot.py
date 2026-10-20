from dataclasses import dataclass
from datetime import datetime

from steward.github.models import DEPENDABOT_LOGIN, RepoRef, graphql_login

# How the hub's GraphQL answers name Dependabot as a pull request author.
DEPENDABOT_AUTHOR = graphql_login(DEPENDABOT_LOGIN)


@dataclass(frozen=True)
class OpenPull:
    number: int
    title: str
    author: str | None
    labels: frozenset[str]


@dataclass(frozen=True)
class OpenIssue:
    number: int
    author: str | None
    body: str


@dataclass(frozen=True)
class HubRepo:
    """What GitHub said about one repository. None means unreadable or truncated, so
    `HubRepo(repo)` is a repository nothing is known about."""

    repo: RepoRef
    ci_state: str | None = None
    last_commit_at: datetime | None = None
    deploy_state: str | None = None
    deploy_at: datetime | None = None
    pulls_open: int | None = None
    pulls: tuple[OpenPull, ...] | None = None
    issues_open: int | None = None
    standards_issues: tuple[OpenIssue, ...] | None = None
    alert_severities: tuple[str, ...] | None = None
