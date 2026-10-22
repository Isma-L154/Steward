from dataclasses import dataclass

from steward.standards.ai_trace import check_no_ai_trace
from steward.standards.dependabot_config import check_dependabot
from steward.standards.docs import check_agents, check_readme
from steward.standards.flow import (
    check_commit_identity,
    check_no_direct_push,
    check_prs_reference_issues,
)
from steward.standards.protection import check_required_checks
from steward.standards.snapshot import Finding, RepoSnapshot
from steward.standards.workflows import (
    check_actions_pinned,
    check_ci_triggers,
    check_concurrency,
    check_permissions,
    parse_workflows,
)


@dataclass(frozen=True)
class Rule:
    id: str
    title: str


RULES: tuple[Rule, ...] = (
    Rule("workflow-unreadable", "Workflow files parse"),
    Rule("ci-triggers", "CI runs on pull requests and on main"),
    Rule("actions-pinned", "Actions are pinned to a commit SHA or a version tag"),
    Rule("permissions", "Every workflow declares permissions"),
    Rule("concurrency", "Every workflow declares concurrency"),
    Rule("dependabot", "Dependabot covers every ecosystem"),
    Rule("required-checks", "Main has required status checks"),
    Rule("direct-push", "Every change reaches main through a pull request"),
    Rule("pr-issue", "Every merged pull request closes an issue"),
    Rule("commit-identity", "Commits use the owner's email"),
    Rule("ai-trace", "No AI attribution in commits, pull requests or branch names"),
    Rule("readme", "README follows the standard"),
    Rule("agents", "AGENTS.md or SECURITY.md decides the seven baseline security controls"),
)
_ORDER = [rule.id for rule in RULES]


def run_checks(
    snapshot: RepoSnapshot, owner_email: str, trusted_bots: frozenset[str]
) -> list[Finding]:
    workflows = parse_workflows(snapshot)
    findings = [
        *check_ci_triggers(snapshot, workflows),
        *check_actions_pinned(workflows),
        *check_permissions(workflows),
        *check_concurrency(workflows),
        *check_dependabot(snapshot),
        *check_required_checks(snapshot),
        *check_no_direct_push(snapshot),
        *check_prs_reference_issues(snapshot, trusted_bots),
        *check_commit_identity(snapshot, owner_email),
        *check_no_ai_trace(snapshot),
        *check_readme(snapshot),
        *check_agents(snapshot),
    ]
    return sorted(findings, key=lambda finding: _ORDER.index(finding.rule))
