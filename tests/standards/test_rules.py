import pytest
import yaml

from steward.standards.rules import RULES, run_checks
from tests.standards.builders import OWNER_EMAIL, commit, snapshot


def test_every_rule_has_a_unique_id_and_a_title() -> None:
    ids = [rule.id for rule in RULES]
    assert len(ids) == len(set(ids))
    assert all(rule.title for rule in RULES)


def test_compliant_repository_has_no_findings() -> None:
    assert run_checks(snapshot(), OWNER_EMAIL) == []


def test_findings_come_in_rule_order() -> None:
    failing = snapshot(required_checks=frozenset(), commits=[commit(from_merged_pr=False)])
    order = [rule.id for rule in RULES]
    rules = [finding.rule for finding in run_checks(failing, OWNER_EMAIL)]
    assert rules == sorted(rules, key=order.index)
    assert set(rules) == {"required-checks", "direct-push"}


def test_every_finding_rule_is_registered() -> None:
    registered = {rule.id for rule in RULES}
    assert {"workflow-unreadable", "ci-triggers", "readme", "agents"} <= registered


def test_each_workflow_is_parsed_once_per_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = snapshot()
    parsed: list[str] = []
    real = yaml.safe_load

    def spy(text: str) -> object:
        parsed.append(text)
        return real(text)

    monkeypatch.setattr(yaml, "safe_load", spy)
    run_checks(repo, OWNER_EMAIL)
    assert sorted(text for text in parsed if text in repo.workflows.values()) == sorted(
        repo.workflows.values()
    )
