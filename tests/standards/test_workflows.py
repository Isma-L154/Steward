import pytest

from steward.standards.snapshot import Finding, RepoSnapshot, code_span
from steward.standards.workflows import (
    Workflows,
    check_actions_pinned,
    check_ci_triggers,
    check_concurrency,
    check_permissions,
    parse_workflows,
)
from tests.standards.builders import CI, DEPLOY, SHA, snapshot


def _all(repo: RepoSnapshot) -> list[Finding]:
    workflows = parse_workflows(repo)
    return [
        *check_ci_triggers(repo, workflows),
        *check_actions_pinned(workflows),
        *check_permissions(workflows),
        *check_concurrency(workflows),
    ]


def _parsed(workflows: dict[str, str]) -> Workflows:
    return parse_workflows(snapshot(workflows=workflows))


def _triggers(workflows: dict[str, str]) -> list[Finding]:
    repo = snapshot(workflows=workflows)
    return check_ci_triggers(repo, parse_workflows(repo))


def test_compliant_workflows_have_no_findings() -> None:
    assert _all(snapshot()) == []


def test_code_span_makes_text_inert() -> None:
    assert code_span("a`b@c\nd.yml") == "`ab@c d.yml`"


def test_no_pull_request_workflow_is_reported() -> None:
    findings = _triggers({"deploy.yml": DEPLOY})
    assert [f.rule for f in findings] == ["ci-triggers"]


def test_no_workflow_on_main_is_reported() -> None:
    findings = _triggers({"ci.yml": CI})
    assert [f.rule for f in findings] == ["ci-triggers"]


def test_one_workflow_on_pull_request_and_push_to_main_is_enough() -> None:
    both = CI.replace("  workflow_call:\n", "  push:\n    branches: [main]\n")
    assert _triggers({"ci.yml": both}) == []


def test_push_without_branch_filter_counts_as_main() -> None:
    both = CI.replace("  workflow_call:\n", "  push:\n")
    assert _triggers({"ci.yml": both}) == []


def test_list_form_of_on_is_understood() -> None:
    listed = CI.replace("on:\n  pull_request:\n  workflow_call:\n", "on: [pull_request, push]\n")
    assert _triggers({"ci.yml": listed}) == []


def test_action_pinned_to_a_branch_is_reported_with_its_file() -> None:
    loose = CI.replace(f"actions/checkout@{SHA}", "actions/checkout@main")
    findings = check_actions_pinned(_parsed({"ci.yml": loose, "deploy.yml": DEPLOY}))
    assert [f.rule for f in findings] == ["actions-pinned"]
    assert "`ci.yml`" in findings[0].detail
    assert "actions/checkout@main" in findings[0].detail


@pytest.mark.parametrize(
    "ref",
    [
        "actions/checkout@v4",
        "actions/checkout@v4.2.1",
        "./x/y",
        "$/.github/actions/x",
        "docker://alpine:3",
    ],
)
def test_tags_shas_local_and_docker_references_pass(ref: str) -> None:
    pinned = CI.replace(f"actions/checkout@{SHA}", ref)
    assert check_actions_pinned(_parsed({"ci.yml": pinned})) == []


def test_workflow_without_permissions_is_reported() -> None:
    bare = CI.replace("permissions:\n  contents: read\n", "")
    findings = check_permissions(_parsed({"ci.yml": bare}))
    assert [f.rule for f in findings] == ["permissions"]


def test_permissions_on_every_job_are_enough() -> None:
    per_job = CI.replace("permissions:\n  contents: read\n", "").replace(
        "    runs-on: ubuntu-latest\n", "    runs-on: ubuntu-latest\n    permissions: {}\n"
    )
    assert check_permissions(_parsed({"ci.yml": per_job})) == []


def test_workflow_without_concurrency_is_reported() -> None:
    bare = CI.replace(
        "concurrency:\n  group: ci-${{ github.ref }}\n  cancel-in-progress: true\n", ""
    )
    findings = check_concurrency(_parsed({"ci.yml": bare}))
    assert [f.rule for f in findings] == ["concurrency"]


def test_unreadable_workflow_is_reported_once_and_skipped() -> None:
    broken = {"ci.yml": CI, "deploy.yml": DEPLOY, "bad.yml": "on: [unclosed\n"}
    findings = _all(snapshot(workflows=broken))
    assert [f.rule for f in findings] == ["workflow-unreadable"]
    assert "`bad.yml`" in findings[0].detail
