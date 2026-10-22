from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from steward.dependabot.decision import (
    MAJOR_BROKEN,
    MAJOR_READY,
    MANAGED_LABELS,
    UPDATE_BLOCKED,
    UPDATE_BROKEN,
    Decision,
    Facts,
    Kind,
    decide,
)
from steward.dependabot.pushes import PushTrust
from steward.dependabot.update_type import UpdateType
from steward.dependabot.verdict import Verdict

MERGEABLE = Facts(
    authored_by_dependabot=True,
    pushes=PushTrust.TRUSTED,
    open=True,
    update_type=UpdateType.MINOR,
    verdict=Verdict.GREEN,
    has_required_checks=True,
    mergeable=True,
    behind_by=0,
    branch_update_requested=False,
)
NOTHING = Decision(Kind.NOTHING)


def test_managed_labels() -> None:
    assert {"major-ready", "major-broken", "update-broken", "update-blocked"} == MANAGED_LABELS


@pytest.mark.parametrize("update_type", [UpdateType.PATCH, UpdateType.MINOR])
def test_green_up_to_date_minor_or_patch_merges(update_type: UpdateType) -> None:
    assert decide(replace(MERGEABLE, update_type=update_type)) == Decision(Kind.MERGE)


@pytest.mark.parametrize(
    "blocked",
    [replace(MERGEABLE, authored_by_dependabot=False), replace(MERGEABLE, open=False)],
)
def test_not_dependabot_or_not_open_does_nothing(blocked: Facts) -> None:
    assert decide(blocked) == NOTHING
    assert decide(replace(blocked, update_type=UpdateType.MAJOR)) == NOTHING


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        (Verdict.GREEN, Decision(Kind.LABEL, MAJOR_READY)),
        (Verdict.RED, Decision(Kind.LABEL, MAJOR_BROKEN)),
        (Verdict.PENDING, NOTHING),
    ],
)
def test_major(verdict: Verdict, expected: Decision) -> None:
    assert decide(replace(MERGEABLE, update_type=UpdateType.MAJOR, verdict=verdict)) == expected


def test_red_minor_is_labelled_broken() -> None:
    assert decide(replace(MERGEABLE, verdict=Verdict.RED)) == Decision(Kind.LABEL, UPDATE_BROKEN)


def test_pending_minor_does_nothing() -> None:
    assert decide(replace(MERGEABLE, verdict=Verdict.PENDING)) == NOTHING


def test_no_required_checks_does_nothing() -> None:
    assert decide(replace(MERGEABLE, has_required_checks=False)) == NOTHING


@pytest.mark.parametrize("mergeable", [False, None])
def test_not_known_mergeable_does_nothing(mergeable: bool | None) -> None:
    assert decide(replace(MERGEABLE, mergeable=mergeable)) == NOTHING


def test_behind_updates_the_branch() -> None:
    assert decide(replace(MERGEABLE, behind_by=2)) == Decision(Kind.UPDATE_BRANCH)


def test_behind_with_branch_update_already_requested_does_nothing() -> None:
    assert decide(replace(MERGEABLE, behind_by=2, branch_update_requested=True)) == NOTHING


@given(
    st.builds(
        Facts,
        authored_by_dependabot=st.booleans(),
        pushes=st.sampled_from(PushTrust),
        open=st.booleans(),
        update_type=st.sampled_from(UpdateType),
        verdict=st.sampled_from(Verdict),
        has_required_checks=st.booleans(),
        mergeable=st.none() | st.booleans(),
        behind_by=st.integers(min_value=0, max_value=50),
        branch_update_requested=st.booleans(),
    )
)
def test_merge_only_for_green_dependabot_minor_or_patch_with_required_checks(
    facts: Facts,
) -> None:
    if decide(facts).kind is Kind.MERGE:
        assert facts.update_type is not UpdateType.MAJOR
        assert facts.verdict is Verdict.GREEN
        assert facts.authored_by_dependabot
        assert facts.pushes is PushTrust.TRUSTED
        assert facts.open
        assert facts.has_required_checks
        assert facts.mergeable is True
        assert facts.behind_by == 0


@pytest.mark.parametrize("update_type", list(UpdateType))
def test_a_push_by_someone_else_blocks_the_update(update_type: UpdateType) -> None:
    facts = replace(MERGEABLE, pushes=PushTrust.UNTRUSTED, update_type=update_type)
    assert decide(facts) == Decision(Kind.LABEL, UPDATE_BLOCKED)


@pytest.mark.parametrize("verdict", list(Verdict))
def test_pushes_not_known_yet_decide_nothing(verdict: Verdict) -> None:
    assert decide(replace(MERGEABLE, pushes=PushTrust.UNKNOWN, verdict=verdict)) == NOTHING
