from collections.abc import Sequence
from datetime import datetime
from typing import Any

from steward.dependabot.decision import MAJOR_BROKEN, MAJOR_READY, UPDATE_BLOCKED, UPDATE_BROKEN
from steward.hub.health import own_standards_issue
from steward.hub.snapshot import DEPENDABOT_AUTHOR, HubRepo
from steward.hub.text import clean_title, iso, issue_url, pull_url, unchecked_findings

_LISTS = {
    "major_ready": MAJOR_READY,
    "major_failing": MAJOR_BROKEN,
    "updates_failing": UPDATE_BROKEN,
    "updates_blocked": UPDATE_BLOCKED,
}


def report(repos: Sequence[HubRepo], now: datetime, app_login: str) -> dict[str, Any]:
    """The `GET /v1/report` body. A repository whose pull requests or standards issue could
    not be read is listed under `unknown`, so it never reads as having nothing pending."""
    body: dict[str, Any] = {"generated_at": iso(now), **{key: [] for key in _LISTS}}
    body["standards"] = []
    body["unknown"] = []
    for repo in sorted(repos, key=lambda repo: repo.repo.full_name):
        if repo.pulls is None or repo.standards_issues is None:
            body["unknown"].append(repo.repo.full_name)
            continue
        dependabot = [pull for pull in repo.pulls if pull.author == DEPENDABOT_AUTHOR]
        for pull in sorted(dependabot, key=lambda pull: pull.number):
            for key, label in _LISTS.items():
                if label in pull.labels:
                    body[key].append(
                        {
                            "repo": repo.repo.full_name,
                            "number": pull.number,
                            "title": clean_title(pull.title),
                            "url": pull_url(repo.repo, pull.number),
                        }
                    )
        issue = own_standards_issue(repo, app_login)
        if issue is not None:
            body["standards"].append(
                {
                    "repo": repo.repo.full_name,
                    "url": issue_url(repo.repo, issue.number),
                    "findings": unchecked_findings(issue.body),
                }
            )
    return body
