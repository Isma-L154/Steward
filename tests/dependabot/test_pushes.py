import pytest

from steward.dependabot.pushes import PushTrust, push_trust
from steward.github.models import BranchActivity, BranchPush

REWRITER = "dependabot[bot]"
TRUSTED = frozenset({REWRITER, "app-steward[bot]"})
CREATED = BranchPush(REWRITER, "aaa", replaces_branch=True)
UPDATED = BranchPush("app-steward[bot]", "bbb")


def _activity(*pushes: BranchPush, complete: bool = True) -> BranchActivity:
    return BranchActivity(pushes, complete)


def test_pushes_by_dependabot_and_steward_up_to_the_head_are_trusted() -> None:
    assert push_trust(_activity(UPDATED, CREATED), TRUSTED, REWRITER, "bbb") is PushTrust.TRUSTED


def test_a_push_by_anyone_else_is_untrusted() -> None:
    spoofed = BranchPush("mallory", "ccc")
    assert push_trust(_activity(spoofed, CREATED), TRUSTED, REWRITER, "ccc") is PushTrust.UNTRUSTED


def test_an_older_push_by_anyone_else_is_untrusted_even_after_a_trusted_one() -> None:
    older = BranchPush("mallory", "bbb")
    assert (
        push_trust(_activity(UPDATED, older, CREATED), TRUSTED, REWRITER, "bbb")
        is PushTrust.UNTRUSTED
    )


def test_a_push_without_an_actor_is_untrusted() -> None:
    assert (
        push_trust(_activity(BranchPush(None, "aaa")), TRUSTED, REWRITER, "aaa")
        is PushTrust.UNTRUSTED
    )


def test_a_listing_behind_the_head_is_unknown() -> None:
    assert push_trust(_activity(CREATED), TRUSTED, REWRITER, "bbb") is PushTrust.UNKNOWN


def test_an_empty_listing_is_unknown() -> None:
    assert push_trust(_activity(), TRUSTED, REWRITER, "aaa") is PushTrust.UNKNOWN


def test_a_possibly_truncated_listing_is_unknown() -> None:
    assert (
        push_trust(_activity(UPDATED, complete=False), TRUSTED, REWRITER, "bbb")
        is PushTrust.UNKNOWN
    )


def test_a_stranger_in_a_truncated_listing_is_still_untrusted() -> None:
    spoofed = BranchPush("mallory", "ccc")
    assert (
        push_trust(_activity(spoofed, complete=False), TRUSTED, REWRITER, "ccc")
        is PushTrust.UNTRUSTED
    )


def test_dependabot_force_push_erases_older_stranger_pushes() -> None:
    rewritten = BranchPush(REWRITER, "new", replaces_branch=True)
    activity = _activity(
        rewritten,
        BranchPush("Isma-L154", "merge3"),
        BranchPush("Isma-L154", "merge2"),
        BranchPush("Isma-L154", "merge1"),
        CREATED,
    )
    assert push_trust(activity, TRUSTED, REWRITER, "new") is PushTrust.TRUSTED


def test_a_stranger_push_after_dependabot_force_push_is_untrusted() -> None:
    rewritten = BranchPush(REWRITER, "new", replaces_branch=True)
    activity = _activity(BranchPush("mallory", "spoofed"), rewritten, CREATED)
    assert push_trust(activity, TRUSTED, REWRITER, "spoofed") is PushTrust.UNTRUSTED


@pytest.mark.parametrize("actor", ["app-steward[bot]", None])
def test_a_force_push_by_anyone_but_dependabot_does_not_reset_history(actor: str | None) -> None:
    rewritten = BranchPush(actor, "new", replaces_branch=True)
    activity = _activity(rewritten, BranchPush("mallory", "old"), CREATED)
    assert push_trust(activity, TRUSTED, REWRITER, "new") is PushTrust.UNTRUSTED


def test_a_truncated_listing_with_a_dependabot_reset_is_trusted() -> None:
    rewritten = BranchPush(REWRITER, "new", replaces_branch=True)
    activity = _activity(UPDATED, rewritten, BranchPush("mallory", "old"), complete=False)
    assert push_trust(activity, TRUSTED, REWRITER, "bbb") is PushTrust.TRUSTED


def test_dependabot_branch_creation_erases_older_stranger_pushes() -> None:
    activity = _activity(CREATED, BranchPush("mallory", "old"))
    assert push_trust(activity, TRUSTED, REWRITER, "aaa") is PushTrust.TRUSTED


def test_a_dependabot_reset_behind_the_head_is_unknown() -> None:
    rewritten = BranchPush(REWRITER, "new", replaces_branch=True)
    activity = _activity(rewritten, BranchPush("mallory", "old"), complete=False)
    assert push_trust(activity, TRUSTED, REWRITER, "head") is PushTrust.UNKNOWN
