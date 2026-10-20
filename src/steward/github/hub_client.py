from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel

from steward.accounts import Accounts
from steward.github.api import GitHubApi
from steward.github.app_auth import InstallationTokens, Signer
from steward.github.client import GitHubClient
from steward.github.http import HttpClient
from steward.github.models import Installation, RepoRef
from steward.hub.snapshot import HubRepo, OpenIssue, OpenPull
from steward.hub.text import is_safe_repo
from steward.repos import is_managed

# Everything the hub reads, and nothing that writes. Contents is needed even though no file
# is read: a private repository returns its default branch and commits only with it.
READ_ONLY_PERMISSIONS: Mapping[str, str] = MappingProxyType(
    {
        "metadata": "read",
        "contents": "read",
        "pull_requests": "read",
        "issues": "read",
        "checks": "read",
        "statuses": "read",
        "deployments": "read",
        "vulnerability_alerts": "read",
    }
)

_FRAGMENT = """
fragment Health on Repository {
  defaultBranchRef {
    target { ... on Commit { committedDate statusCheckRollup { state } } }
  }
  deployments(environments: ["production"], first: 1,
              orderBy: {field: CREATED_AT, direction: DESC}) {
    nodes { createdAt latestStatus { state } }
  }
  pullRequests(states: OPEN, first: 100) {
    totalCount
    nodes { number title author { login } labels(first: 20) { nodes { name } } }
  }
  issues(states: OPEN) { totalCount }
  standards: issues(states: OPEN, labels: [$label], first: 5) {
    totalCount
    nodes { number author { login } body }
  }
  vulnerabilityAlerts(states: OPEN, first: 100) {
    totalCount
    nodes { securityVulnerability { severity } }
  }
}
"""


class _Model(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="ignore", frozen=True, alias_generator=to_camel, populate_by_name=True
    )


class _State(_Model):
    state: str


class _Target(_Model):
    committed_date: str | None = None
    status_check_rollup: _State | None = None


class _Ref(_Model):
    target: _Target | None = None


class _Deployment(_Model):
    created_at: str
    latest_status: _State | None = None


class _Deployments(_Model):
    nodes: list[_Deployment]


class _Login(_Model):
    login: str


class _Label(_Model):
    name: str


class _Labels(_Model):
    nodes: list[_Label]


class _Pull(_Model):
    number: int
    title: str
    author: _Login | None = None
    labels: _Labels


class _Pulls(_Model):
    total_count: int
    nodes: list[_Pull]


class _Count(_Model):
    total_count: int


class _Issue(_Model):
    number: int
    author: _Login | None = None
    body: str


class _Issues(_Model):
    total_count: int
    nodes: list[_Issue]


class _Vulnerability(_Model):
    severity: str


class _Alert(_Model):
    security_vulnerability: _Vulnerability | None = None


class _Alerts(_Model):
    total_count: int
    nodes: list[_Alert]


class _Repository(_Model):
    default_branch_ref: _Ref | None = None
    deployments: _Deployments | None = None
    pull_requests: _Pulls | None = None
    issues: _Count | None = None
    standards: _Issues | None = None
    vulnerability_alerts: _Alerts | None = None


def read_only_tokens(
    http: HttpClient, app_id: str, signer: Signer, clock: Callable[[], float]
) -> InstallationTokens:
    return InstallationTokens(http, app_id, signer, clock, READ_ONLY_PERMISSIONS)


def build_query(count: int) -> str:
    """One aliased block per repository; owners and names only ever travel as variables."""
    declarations = ", ".join(
        ["$label: String!", *(f"$o{i}: String!, $n{i}: String!" for i in range(count))]
    )
    blocks = "\n".join(
        f"  r{i}: repository(owner: $o{i}, name: $n{i}) {{ ...Health }}" for i in range(count)
    )
    return f"query({declarations}) {{\n{blocks}\n}}\n{_FRAGMENT}"


def _moment(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _complete[T](total: int, nodes: list[T]) -> tuple[T, ...] | None:
    # A connection with more items than were returned would undercount: unknown instead.
    return tuple(nodes) if total <= len(nodes) else None


def _parse(repo: RepoRef, block: _Repository) -> HubRepo:
    target = block.default_branch_ref.target if block.default_branch_ref else None
    deployment = (
        block.deployments.nodes[0] if block.deployments and block.deployments.nodes else None
    )
    pulls = block.pull_requests
    standards = block.standards
    alerts = block.vulnerability_alerts
    return HubRepo(
        repo,
        ci_state=target.status_check_rollup.state
        if target and target.status_check_rollup
        else None,
        last_commit_at=_moment(target.committed_date) if target else None,
        deploy_state=(
            deployment.latest_status.state if deployment and deployment.latest_status else None
        ),
        deploy_at=_moment(deployment.created_at) if deployment else None,
        pulls_open=pulls.total_count if pulls else None,
        pulls=_complete(
            pulls.total_count,
            [
                OpenPull(
                    pull.number,
                    pull.title,
                    pull.author.login if pull.author else None,
                    frozenset(label.name for label in pull.labels.nodes),
                )
                for pull in pulls.nodes
            ],
        )
        if pulls
        else None,
        issues_open=block.issues.total_count if block.issues else None,
        standards_issues=_complete(
            standards.total_count,
            [
                OpenIssue(issue.number, issue.author.login if issue.author else None, issue.body)
                for issue in standards.nodes
            ],
        )
        if standards
        else None,
        alert_severities=_complete(
            alerts.total_count,
            [
                alert.security_vulnerability.severity if alert.security_vulnerability else "UNKNOWN"
                for alert in alerts.nodes
            ],
        )
        if alerts
        else None,
    )


def parse_repo(repo: RepoRef, block: Any) -> HubRepo:
    """Anything in the block that is not the expected shape makes the whole repository
    unknown, never partly guessed."""
    if block is None:
        return HubRepo(repo)
    try:
        return _parse(repo, _Repository.model_validate(block))
    except ValidationError, ValueError:
        return HubRepo(repo)


class HubClient:
    """Reads every managed repository of one installation in three calls."""

    def __init__(self, api: GitHubApi, standards_label: str) -> None:
        self._api = api
        self._standards_label = standards_label

    async def repos(self) -> list[HubRepo]:
        installed = await GitHubClient(self._api).installed_repositories()
        repos = [
            item.repo
            for item in installed
            if is_managed(item.archived, item.topics) and is_safe_repo(item.repo)
        ]
        if not repos:
            return []
        variables = {"label": self._standards_label}
        for index, repo in enumerate(repos):
            variables[f"o{index}"] = repo.owner
            variables[f"n{index}"] = repo.name
        data = await self._api.graphql_partial(build_query(len(repos)), variables)
        return [parse_repo(repo, data.get(f"r{index}")) for index, repo in enumerate(repos)]


async def account_repos(
    installations: Sequence[Installation],
    accounts: Accounts,
    client_for: Callable[[int], HubClient],
) -> list[HubRepo]:
    """The owner's repositories only: other allowed accounts trust Steward with merges, not
    with showing their private repositories on the owner's hub."""
    repos: list[HubRepo] = []
    for installation in installations:
        if accounts.is_owner(installation.account):
            repos.extend(await client_for(installation.id).repos())
    return repos
