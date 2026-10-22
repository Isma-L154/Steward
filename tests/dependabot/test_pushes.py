from steward.dependabot.pushes import PushTrust, push_trust
from steward.github.models import BranchActivity, BranchPush

TRUSTED = frozenset({"dependabot[bot]", "app-steward[bot]"})
CREATED = BranchPush("dependabot[bot]", "aaa")
UPDATED = BranchPush("app-steward[bot]", "bbb")


def _activity(*pushes: BranchPush, complete: bool = True) -> BranchActivity:
    return BranchActivity(pushes, complete)


def test_pushes_by_dependabot_and_steward_up_to_the_head_are_trusted() -> None:
    assert push_trust(_activity(UPDATED, CREATED), TRUSTED, "bbb") is PushTrust.TRUSTED


def test_a_push_by_anyone_else_is_untrusted() -> None:
    spoofed = BranchPush("mallory", "ccc")
    assert push_trust(_activity(spoofed, CREATED), TRUSTED, "ccc") is PushTrust.UNTRUSTED


def test_an_older_push_by_anyone_else_is_untrusted_even_after_a_trusted_one() -> None:
    older = BranchPush("mallory", "bbb")
    assert push_trust(_activity(UPDATED, older, CREATED), TRUSTED, "bbb") is PushTrust.UNTRUSTED


def test_a_push_without_an_actor_is_untrusted() -> None:
    assert push_trust(_activity(BranchPush(None, "aaa")), TRUSTED, "aaa") is PushTrust.UNTRUSTED


def test_a_listing_behind_the_head_is_unknown() -> None:
    assert push_trust(_activity(CREATED), TRUSTED, "bbb") is PushTrust.UNKNOWN


def test_an_empty_listing_is_unknown() -> None:
    assert push_trust(_activity(), TRUSTED, "aaa") is PushTrust.UNKNOWN


def test_a_possibly_truncated_listing_is_unknown() -> None:
    assert push_trust(_activity(UPDATED, complete=False), TRUSTED, "bbb") is PushTrust.UNKNOWN


def test_a_stranger_in_a_truncated_listing_is_still_untrusted() -> None:
    spoofed = BranchPush("mallory", "ccc")
    assert push_trust(_activity(spoofed, complete=False), TRUSTED, "ccc") is PushTrust.UNTRUSTED
