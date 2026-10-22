from enum import StrEnum

from steward.github.models import BranchActivity


class PushTrust(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"
    UNKNOWN = "unknown"


def push_trust(activity: BranchActivity, trusted: frozenset[str], head_sha: str) -> PushTrust:
    """Who pushed to the branch, as GitHub authenticated them. A commit's author is whatever
    its author email claims, so it proves nothing about who put the commit there."""
    if any(push.actor not in trusted for push in activity.pushes):
        return PushTrust.UNTRUSTED
    if not activity.complete or not activity.pushes or activity.pushes[0].after != head_sha:
        return PushTrust.UNKNOWN
    return PushTrust.TRUSTED
