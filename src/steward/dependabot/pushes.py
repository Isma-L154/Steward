from enum import StrEnum

from steward.github.models import BranchActivity


class PushTrust(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"
    UNKNOWN = "unknown"


def push_trust(
    activity: BranchActivity, trusted: frozenset[str], rewriter: str, head_sha: str
) -> PushTrust:
    """Who pushed to the branch, as GitHub authenticated them. A commit's author is whatever
    its author email claims, so it proves nothing about who put the commit there.
    History before Dependabot's rewrite is ignored: it never keeps other people's commits.
    """
    complete = activity.complete
    for push in activity.pushes:
        if push.actor not in trusted:
            return PushTrust.UNTRUSTED
        if push.replaces_branch and push.actor == rewriter:
            complete = True
            break
    if not complete or not activity.pushes or activity.pushes[0].after != head_sha:
        return PushTrust.UNKNOWN
    return PushTrust.TRUSTED
