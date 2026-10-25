import re
from collections.abc import Sequence
from itertools import groupby

from steward.github.models import RepoRef
from steward.standards.rules import RULES
from steward.standards.snapshot import WINDOW_DAYS, Finding

ISSUE_TITLE = "Repository standards"
ISSUE_LABEL = "standards"
_TITLES = {rule.id: rule.title for rule in RULES}
_FOOTER = (
    "Kept up to date by Steward on every push to the default branch and every Monday. "
    f"Commits are checked over the last {WINDOW_DAYS} days. "
    "Closing this issue dismisses the findings it lists."
)
_ITEM = re.compile(r"^- \[[ xX]\] (.+)$", re.MULTILINE)


def listed_findings(body: str) -> frozenset[str]:
    return frozenset(detail.strip() for detail in _ITEM.findall(body))


def render_body(repo: RepoRef, findings: Sequence[Finding]) -> str:
    if not findings:
        return f"Nothing left to fix in `{repo.full_name}`.\n\n{_FOOTER}\n"
    sections = [
        f"### {_TITLES[rule]}\n\n" + "\n".join(f"- [ ] {finding.detail}" for finding in group)
        for rule, group in groupby(findings, key=lambda finding: finding.rule)
    ]
    return (
        f"`{repo.full_name}` breaks {len(sections)} of the owner's rules.\n\n"
        + "\n\n".join(sections)
        + f"\n\n---\n{_FOOTER}\n"
    )
