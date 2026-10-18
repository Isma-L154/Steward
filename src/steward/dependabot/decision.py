from dataclasses import dataclass
from enum import StrEnum

from steward.dependabot.update_type import UpdateType
from steward.dependabot.verdict import Verdict

MAJOR_READY = "major-ready"
MAJOR_BROKEN = "major-broken"
UPDATE_BROKEN = "update-broken"
UPDATE_BLOCKED = "update-blocked"
MANAGED_LABELS = frozenset({MAJOR_READY, MAJOR_BROKEN, UPDATE_BROKEN, UPDATE_BLOCKED})


class Kind(StrEnum):
    NOTHING = "nothing"
    LABEL = "label"
    UPDATE_BRANCH = "update_branch"
    MERGE = "merge"


@dataclass(frozen=True)
class Decision:
    kind: Kind
    label: str | None = None


@dataclass(frozen=True)
class Facts:
    authored_by_dependabot: bool
    open: bool
    update_type: UpdateType
    verdict: Verdict
    has_required_checks: bool
    mergeable: bool | None
    behind_by: int
    branch_update_requested: bool


_NOTHING = Decision(Kind.NOTHING)
_MAJOR_LABELS = {Verdict.GREEN: MAJOR_READY, Verdict.RED: MAJOR_BROKEN}


def decide(facts: Facts) -> Decision:
    if not (facts.authored_by_dependabot and facts.open):
        return _NOTHING
    if facts.update_type is UpdateType.MAJOR:
        return _decide_major(facts.verdict)
    return _decide_minor_or_patch(facts)


def _decide_major(verdict: Verdict) -> Decision:
    label = _MAJOR_LABELS.get(verdict)
    return _NOTHING if label is None else Decision(Kind.LABEL, label)


def _decide_minor_or_patch(facts: Facts) -> Decision:
    if facts.verdict is Verdict.RED:
        return Decision(Kind.LABEL, UPDATE_BROKEN)
    # Without required checks nothing guarantees CI ran, so the App fails closed.
    if (
        facts.verdict is Verdict.PENDING
        or not facts.has_required_checks
        or facts.mergeable is not True
    ):
        return _NOTHING
    if facts.behind_by > 0:
        return _NOTHING if facts.branch_update_requested else Decision(Kind.UPDATE_BRANCH)
    return Decision(Kind.MERGE)
