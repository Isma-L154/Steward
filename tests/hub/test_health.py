from datetime import UTC, datetime

import pytest

from steward.github.models import RepoRef
from steward.hub.health import ci_status, deploy_status, health
from steward.hub.snapshot import DEPENDABOT_AUTHOR, HubRepo, OpenIssue, OpenPull

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
REPO = RepoRef("Isma-L154", "nextsode")
APP = "app-steward"


def _pull(number: int, author: str | None = DEPENDABOT_AUTHOR) -> OpenPull:
    return OpenPull(number, f"Bump x to {number}", author, frozenset())


def _entry(repo: HubRepo) -> dict[str, object]:
    entries = health([repo], NOW, APP)["repositories"]
    assert len(entries) == 1
    entry: dict[str, object] = entries[0]
    return entry


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("SUCCESS", "passing"),
        ("FAILURE", "failing"),
        ("ERROR", "failing"),
        ("PENDING", "running"),
        ("EXPECTED", "running"),
        (None, "unknown"),
        ("WEIRD", "unknown"),
    ],
)
def test_ci_mapping(state: str | None, expected: str) -> None:
    assert ci_status(state) == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("SUCCESS", "succeeded"),
        ("FAILURE", "failed"),
        ("ERROR", "failed"),
        ("PENDING", "running"),
        ("QUEUED", "running"),
        ("IN_PROGRESS", "running"),
        ("WAITING", "running"),
        ("INACTIVE", "unknown"),
        (None, "unknown"),
        ("WEIRD", "unknown"),
    ],
)
def test_deploy_mapping(state: str | None, expected: str) -> None:
    assert deploy_status(state) == expected


def test_health_keys_are_exactly_the_contract() -> None:
    known = HubRepo(
        REPO,
        ci_state="SUCCESS",
        last_commit_at=NOW,
        deploy_state="SUCCESS",
        deploy_at=NOW,
        pulls_open=1,
        pulls=(_pull(3),),
        issues_open=0,
        standards_issues=(),
        alert_severities=(),
    )
    body = health([known], NOW, APP)
    assert set(body) == {"generated_at", "repositories"}
    assert body["generated_at"] == "2026-10-19T12:00:00Z"
    entry = body["repositories"][0]
    assert set(entry) == {
        "repo",
        "url",
        "ci",
        "deploy",
        "last_commit_at",
        "pull_requests",
        "issues",
        "security_alerts",
        "standards",
    }
    assert entry["repo"] == "Isma-L154/nextsode"
    assert entry["url"] == "https://github.com/Isma-L154/nextsode"
    assert entry["ci"] == "passing"
    assert entry["deploy"] == {"state": "succeeded", "at": "2026-10-19T12:00:00Z"}
    assert entry["last_commit_at"] == "2026-10-19T12:00:00Z"
    assert entry["pull_requests"] == {"open": 1, "dependabot": 1}
    assert entry["issues"] == {"open": 0}
    assert entry["security_alerts"] == {"critical": 0, "high": 0, "medium": 0, "low": 0}
    assert entry["standards"] == {"state": "passing", "url": None, "findings": None}


def test_unknown_repo_reads_unknown_everywhere() -> None:
    entry = _entry(HubRepo(REPO))
    assert entry["ci"] == "unknown"
    assert entry["deploy"] == {"state": "unknown", "at": None}
    assert entry["last_commit_at"] is None
    assert entry["pull_requests"] is None
    assert entry["issues"] is None
    assert entry["security_alerts"] is None
    assert entry["standards"] == {"state": "unknown", "url": None, "findings": None}


def test_dependabot_counted_by_author_and_null_when_truncated() -> None:
    pulls = (_pull(1), _pull(2), _pull(3, author="Isma-L154"))
    assert _entry(HubRepo(REPO, pulls_open=3, pulls=pulls))["pull_requests"] == {
        "open": 3,
        "dependabot": 2,
    }
    assert _entry(HubRepo(REPO, pulls_open=150, pulls=None))["pull_requests"] == {
        "open": 150,
        "dependabot": None,
    }


def test_alerts_by_severity() -> None:
    severities = ("CRITICAL", "HIGH", "HIGH", "MODERATE")
    assert _entry(HubRepo(REPO, alert_severities=severities))["security_alerts"] == {
        "critical": 1,
        "high": 2,
        "medium": 1,
        "low": 0,
    }
    odd = ("HIGH", "SEVERE")
    assert _entry(HubRepo(REPO, alert_severities=odd))["security_alerts"] is None


def test_standards_only_counts_the_apps_issue() -> None:
    own = OpenIssue(7, APP, "- [ ] a\n- [ ] b\n- [x] c")
    foreign = OpenIssue(9, "mallory", "- [ ] fake")
    assert _entry(HubRepo(REPO, standards_issues=(foreign, own)))["standards"] == {
        "state": "failing",
        "url": "https://github.com/Isma-L154/nextsode/issues/7",
        "findings": 2,
    }
    assert _entry(HubRepo(REPO, standards_issues=(foreign,)))["standards"] == {
        "state": "passing",
        "url": None,
        "findings": None,
    }
    assert _entry(HubRepo(REPO, standards_issues=None))["standards"]["state"] == "unknown"  # type: ignore[index]


def test_repositories_sorted_by_repo() -> None:
    repos = [HubRepo(RepoRef("b", "z")), HubRepo(RepoRef("a", "y")), HubRepo(RepoRef("a", "x"))]
    names = [entry["repo"] for entry in health(repos, NOW, APP)["repositories"]]
    assert names == ["a/x", "a/y", "b/z"]
