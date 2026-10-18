from steward.standards.protection import check_required_checks
from tests.standards.builders import snapshot


def test_required_checks_present_pass() -> None:
    assert check_required_checks(snapshot()) == []


def test_no_required_checks_is_reported() -> None:
    findings = check_required_checks(snapshot(required_checks=frozenset()))
    assert [f.rule for f in findings] == ["required-checks"]
