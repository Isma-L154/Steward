from datetime import UTC, datetime

import pytest

from steward.dependabot.decision import MAJOR_BROKEN, MAJOR_READY, UPDATE_BLOCKED, UPDATE_BROKEN
from steward.github.models import RepoRef
from steward.hub.report import report
from steward.hub.snapshot import DEPENDABOT_LOGIN, HubRepo, OpenIssue, OpenPull

NOW = datetime(2026, 10, 19, 6, 3, 12, tzinfo=UTC)
REPO = RepoRef("Isma-L154", "hub")
APP = "app-steward"
LISTS = ("major_ready", "major_failing", "updates_failing", "updates_blocked")


def _repo(*pulls: OpenPull, issues: tuple[OpenIssue, ...] = (), repo: RepoRef = REPO) -> HubRepo:
    return HubRepo(repo, pulls_open=len(pulls), pulls=pulls, standards_issues=issues)


def _pull(number: int, label: str, author: str = DEPENDABOT_LOGIN, title: str = "Bump") -> OpenPull:
    return OpenPull(number, title, author, frozenset({label}))


def test_keys_and_generation_time() -> None:
    body = report([], NOW, APP)
    assert set(body) == {"generated_at", *LISTS, "standards", "unknown"}
    assert body["generated_at"] == "2026-10-19T06:03:12Z"
    assert all(body[key] == [] for key in (*LISTS, "standards", "unknown"))


@pytest.mark.parametrize(
    ("label", "key"),
    [
        (MAJOR_READY, "major_ready"),
        (MAJOR_BROKEN, "major_failing"),
        (UPDATE_BROKEN, "updates_failing"),
        (UPDATE_BLOCKED, "updates_blocked"),
    ],
)
def test_each_label_lands_in_its_list(label: str, key: str) -> None:
    title = "Bump wrangler\u0007 from 4.x to 5.0"
    body = report([_repo(_pull(12, label, title=title))], NOW, APP)
    assert body[key] == [
        {
            "repo": "Isma-L154/hub",
            "number": 12,
            "title": "Bump wrangler from 4.x to 5.0",
            "url": "https://github.com/Isma-L154/hub/pull/12",
        }
    ]
    assert all(body[other] == [] for other in LISTS if other != key)


def test_non_dependabot_pr_with_label_is_excluded() -> None:
    body = report([_repo(_pull(5, MAJOR_READY, author="mallory"))], NOW, APP)
    assert all(body[key] == [] for key in LISTS)


def test_standards_lists_only_the_apps_open_issue() -> None:
    issues = (OpenIssue(3, "mallory", "- [ ] x"), OpenIssue(7, APP, "- [ ] a\n- [ ] b"))
    body = report([_repo(issues=issues)], NOW, APP)
    assert body["standards"] == [
        {"repo": "Isma-L154/hub", "url": "https://github.com/Isma-L154/hub/issues/7", "findings": 2}
    ]


def test_unreadable_repo_goes_to_unknown() -> None:
    no_pulls = HubRepo(RepoRef("a", "x"), pulls=None, standards_issues=(OpenIssue(1, APP, ""),))
    no_issues = HubRepo(
        RepoRef("a", "y"), pulls_open=1, pulls=(_pull(2, MAJOR_READY),), standards_issues=None
    )
    body = report([no_issues, no_pulls], NOW, APP)
    assert body["unknown"] == ["a/x", "a/y"]
    assert all(body[key] == [] for key in (*LISTS, "standards"))


def test_items_sorted_by_repo_then_number() -> None:
    first = _repo(_pull(9, MAJOR_READY), _pull(2, MAJOR_READY), repo=RepoRef("b", "z"))
    second = _repo(_pull(4, MAJOR_READY), repo=RepoRef("a", "y"))
    order = [
        (item["repo"], item["number"]) for item in report([first, second], NOW, APP)["major_ready"]
    ]
    assert order == [("a/y", 4), ("b/z", 2), ("b/z", 9)]
