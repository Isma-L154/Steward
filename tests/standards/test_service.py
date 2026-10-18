from datetime import UTC, datetime, timedelta

from steward.github.standards_client import TrackingIssue
from steward.standards.report import render_body
from steward.standards.service import StandardsService
from tests.standards.builders import OWNER_EMAIL, snapshot
from tests.standards.fakes import FakeStandardsGitHub

NOW = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)
FAILING = snapshot(required_checks=frozenset())
PASSING = snapshot()


def _service(github: FakeStandardsGitHub) -> StandardsService:
    return StandardsService(github, OWNER_EMAIL, "app-steward[bot]", lambda: NOW)


def _failing_body() -> str:
    from steward.standards.rules import run_checks  # noqa: PLC0415

    trusted = frozenset({"dependabot", "dependabot[bot]", "app-steward", "app-steward[bot]"})
    return render_body(FAILING.repo, run_checks(FAILING, OWNER_EMAIL, trusted))


async def test_failing_repository_without_issue_gets_one() -> None:
    github = FakeStandardsGitHub(FAILING)
    findings = await _service(github).audit(FAILING.repo)
    assert [f.rule for f in findings] == ["required-checks"]
    assert github.writes == [("create", "Repository standards", _failing_body(), "standards")]


async def test_same_findings_and_open_issue_write_nothing() -> None:
    github = FakeStandardsGitHub(FAILING, TrackingIssue(7, "open", _failing_body()))
    await _service(github).audit(FAILING.repo)
    assert github.writes == []


async def test_line_endings_do_not_count_as_a_change() -> None:
    body = _failing_body().replace("\n", "\r\n") + "\r\n"
    github = FakeStandardsGitHub(FAILING, TrackingIssue(7, "open", body))
    await _service(github).audit(FAILING.repo)
    assert github.writes == []


async def test_changed_findings_update_the_open_issue() -> None:
    github = FakeStandardsGitHub(FAILING, TrackingIssue(7, "open", "old body"))
    await _service(github).audit(FAILING.repo)
    assert github.writes == [("update", 7, _failing_body(), "open")]


async def test_regression_reopens_the_closed_issue() -> None:
    github = FakeStandardsGitHub(FAILING, TrackingIssue(7, "closed", "All rules pass"))
    await _service(github).audit(FAILING.repo)
    assert github.writes == [("update", 7, _failing_body(), "open")]


async def test_passing_repository_closes_its_open_issue() -> None:
    github = FakeStandardsGitHub(PASSING, TrackingIssue(7, "open", "old body"))
    assert await _service(github).audit(PASSING.repo) == []
    assert github.writes == [("update", 7, render_body(PASSING.repo, []), "closed")]


async def test_passing_repository_without_issue_writes_nothing() -> None:
    github = FakeStandardsGitHub(PASSING)
    await _service(github).audit(PASSING.repo)
    assert github.writes == []


async def test_passing_repository_with_closed_issue_writes_nothing() -> None:
    github = FakeStandardsGitHub(PASSING, TrackingIssue(7, "closed", "x"))
    await _service(github).audit(PASSING.repo)
    assert github.writes == []


async def test_empty_repository_is_skipped() -> None:
    github = FakeStandardsGitHub(None)
    assert await _service(github).audit(PASSING.repo) == []
    assert github.writes == []


async def test_snapshot_covers_the_last_30_days() -> None:
    github = FakeStandardsGitHub(PASSING)
    await _service(github).audit(PASSING.repo)
    assert github.asked_since == NOW - timedelta(days=30)
