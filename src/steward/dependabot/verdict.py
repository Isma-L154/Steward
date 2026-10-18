from collections.abc import Sequence
from enum import StrEnum

from steward.github.models import CheckResult, CheckState


class Verdict(StrEnum):
    GREEN = "green"
    RED = "red"
    PENDING = "pending"


def ci_verdict(results: Sequence[CheckResult], required: frozenset[str]) -> Verdict:
    states = {result.state for result in results}
    if CheckState.FAILURE in states:
        return Verdict.RED
    if CheckState.PENDING in states:
        return Verdict.PENDING
    # A required check that never reported (a renamed job, say) must not count as passing.
    if not required <= {result.name for result in results}:
        return Verdict.PENDING
    if not results:
        return Verdict.PENDING
    return Verdict.GREEN
