from steward.standards.rules import RULES, run_checks
from tests.standards.builders import OWNER_EMAIL, commit, snapshot

TRUSTED = frozenset({"dependabot", "dependabot[bot]", "app-steward", "app-steward[bot]"})


def test_every_rule_has_a_unique_id_and_a_title() -> None:
    ids = [rule.id for rule in RULES]
    assert len(ids) == len(set(ids))
    assert all(rule.title for rule in RULES)


def test_compliant_repository_has_no_findings() -> None:
    assert run_checks(snapshot(), OWNER_EMAIL, TRUSTED) == []


def test_findings_come_in_rule_order() -> None:
    failing = snapshot(required_checks=frozenset(), commits=[commit(from_merged_pr=False)])
    order = [rule.id for rule in RULES]
    rules = [finding.rule for finding in run_checks(failing, OWNER_EMAIL, TRUSTED)]
    assert rules == sorted(rules, key=order.index)
    assert set(rules) == {"required-checks", "direct-push"}


def test_every_finding_rule_is_registered() -> None:
    registered = {rule.id for rule in RULES}
    assert {"workflow-unreadable", "ci-triggers", "readme", "agents", "ai-trace"} <= registered
