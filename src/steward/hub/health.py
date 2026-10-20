from collections.abc import Sequence
from datetime import datetime
from typing import Any

from steward.hub.snapshot import DEPENDABOT_AUTHOR, HubRepo, OpenIssue
from steward.hub.text import iso, issue_url, repo_url, unchecked_findings

_CI = {
    "SUCCESS": "passing",
    "FAILURE": "failing",
    "ERROR": "failing",
    "PENDING": "running",
    "EXPECTED": "running",
}
# INACTIVE marks a deployment a newer one replaced, so it says nothing about the latest.
_DEPLOY = {
    "SUCCESS": "succeeded",
    "FAILURE": "failed",
    "ERROR": "failed",
    "PENDING": "running",
    "QUEUED": "running",
    "IN_PROGRESS": "running",
    "WAITING": "running",
}
_SEVERITIES = {"CRITICAL": "critical", "HIGH": "high", "MODERATE": "medium", "LOW": "low"}


def ci_status(state: str | None) -> str:
    return _CI.get(state or "", "unknown")


def deploy_status(state: str | None) -> str:
    return _DEPLOY.get(state or "", "unknown")


def own_standards_issue(repo: HubRepo, app_login: str) -> OpenIssue | None:
    own = [issue for issue in repo.standards_issues or () if issue.author == app_login]
    return min(own, key=lambda issue: issue.number, default=None)


def _pull_requests(repo: HubRepo) -> dict[str, Any] | None:
    if repo.pulls_open is None:
        return None
    dependabot = (
        None
        if repo.pulls is None
        else sum(1 for pull in repo.pulls if pull.author == DEPENDABOT_AUTHOR)
    )
    return {"open": repo.pulls_open, "dependabot": dependabot}


def _security_alerts(repo: HubRepo) -> dict[str, int] | None:
    if repo.alert_severities is None or any(
        severity not in _SEVERITIES for severity in repo.alert_severities
    ):
        return None
    counts = dict.fromkeys(_SEVERITIES.values(), 0)
    for severity in repo.alert_severities:
        counts[_SEVERITIES[severity]] += 1
    return counts


def _standards(repo: HubRepo, app_login: str) -> dict[str, Any]:
    if repo.standards_issues is None:
        return {"state": "unknown", "url": None, "findings": None}
    issue = own_standards_issue(repo, app_login)
    if issue is None:
        return {"state": "passing", "url": None, "findings": None}
    return {
        "state": "failing",
        "url": issue_url(repo.repo, issue.number),
        "findings": unchecked_findings(issue.body),
    }


def _entry(repo: HubRepo, app_login: str) -> dict[str, Any]:
    return {
        "repo": repo.repo.full_name,
        "url": repo_url(repo.repo),
        "ci": ci_status(repo.ci_state),
        "deploy": {"state": deploy_status(repo.deploy_state), "at": iso(repo.deploy_at)},
        "last_commit_at": iso(repo.last_commit_at),
        "pull_requests": _pull_requests(repo),
        "issues": None if repo.issues_open is None else {"open": repo.issues_open},
        "security_alerts": _security_alerts(repo),
        "standards": _standards(repo, app_login),
    }


def health(repos: Sequence[HubRepo], now: datetime, app_login: str) -> dict[str, Any]:
    """The `GET /v1/health` body, built field by field so nothing from GitHub passes through."""
    ordered = sorted(repos, key=lambda repo: repo.repo.full_name)
    return {"generated_at": iso(now), "repositories": [_entry(r, app_login) for r in ordered]}
