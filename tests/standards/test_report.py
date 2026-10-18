import re

from steward.github.models import RepoRef
from steward.standards.report import ISSUE_LABEL, ISSUE_TITLE, render_body
from steward.standards.rules import RULES
from steward.standards.snapshot import Finding, code_span

REPO = RepoRef("Isma-L154", "example")


def _outside_code(text: str) -> str:
    return re.sub(r"`[^`]*`", "", text)


def test_constants() -> None:
    assert ISSUE_TITLE == "Repository standards"
    assert ISSUE_LABEL == "standards"


def test_findings_are_grouped_under_their_rule_title_once() -> None:
    findings = [
        Finding("actions-pinned", "`ci.yml` uses unpinned actions"),
        Finding("actions-pinned", "`deploy.yml` uses unpinned actions"),
        Finding("readme", "`README.md` lacks status badges"),
    ]
    body = render_body(REPO, findings)
    titles = {rule.id: rule.title for rule in RULES}
    assert body.count(titles["actions-pinned"]) == 1
    assert body.count(titles["readme"]) == 1
    assert body.count("- [ ] ") == 3


def test_hostile_file_name_stays_inert() -> None:
    hostile = Finding("permissions", f"{code_span('a`b@everyone\n.yml')} declares no permissions")
    body = render_body(REPO, [hostile])
    assert "@" not in _outside_code(body)
    assert "\n.yml" not in body


def test_body_never_mentions_anyone() -> None:
    body = render_body(
        REPO, [Finding("ai-trace", "Commit [abc1234](https://x) carries an AI attribution")]
    )
    assert "@" not in _outside_code(body)


def test_empty_findings_say_all_rules_pass() -> None:
    assert "All rules pass" in render_body(REPO, [])
