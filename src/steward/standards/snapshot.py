from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from steward.github.models import RepoRef

WINDOW_DAYS = 30


@dataclass(frozen=True)
class CommitInfo:
    oid: str
    author_email: str
    author_login: str | None
    is_root: bool
    from_merged_pr: bool


@dataclass(frozen=True)
class RepoSnapshot:
    repo: RepoRef
    default_branch: str
    readme: str | None
    agents: str | None
    security: str | None
    dependabot: str | None
    workflows: Mapping[str, str]
    paths: frozenset[str]
    required_checks: frozenset[str]
    commits: Sequence[CommitInfo]


@dataclass(frozen=True)
class Finding:
    rule: str
    detail: str


def code_span(text: str) -> str:
    """Repository-derived text as inert inline code: GitHub links nothing inside a code span."""
    return "`" + " ".join(text.replace("`", "").split()) + "`"
