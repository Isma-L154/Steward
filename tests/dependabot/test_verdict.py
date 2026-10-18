from steward.dependabot.verdict import Verdict, ci_verdict
from steward.github.models import CheckResult, CheckState

OK = CheckState.SUCCESS
FAIL = CheckState.FAILURE
WAIT = CheckState.PENDING


def test_all_success_with_required_present_is_green() -> None:
    results = [CheckResult("lint", OK), CheckResult("test", OK)]
    assert ci_verdict(results, frozenset({"test"})) == Verdict.GREEN


def test_all_success_without_required_checks_is_green() -> None:
    assert ci_verdict([CheckResult("lint", OK)], frozenset()) == Verdict.GREEN


def test_any_failure_is_red_even_if_others_pending() -> None:
    results = [CheckResult("lint", FAIL), CheckResult("test", WAIT)]
    assert ci_verdict(results, frozenset({"test"})) == Verdict.RED


def test_any_pending_is_pending() -> None:
    results = [CheckResult("lint", OK), CheckResult("test", WAIT)]
    assert ci_verdict(results, frozenset({"test"})) == Verdict.PENDING


def test_required_check_never_reported_is_pending() -> None:
    assert ci_verdict([CheckResult("lint", OK)], frozenset({"test"})) == Verdict.PENDING


def test_no_results_is_pending() -> None:
    assert ci_verdict([], frozenset()) == Verdict.PENDING
