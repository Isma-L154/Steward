from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from steward.dependabot.decision import (
    MAJOR_BROKEN,
    MAJOR_READY,
    MANAGED_LABELS,
    UPDATE_BROKEN,
    Decision,
    Facts,
    Kind,
    decide,
)
from steward.dependabot.update_type import UpdateType
from steward.dependabot.verdict import Verdict

MERGEABLE = Facts(
    authored_by_dependabot=True,
    open=True,
    update_type=UpdateType.MINOR,
    verdict=Verdict.GREEN,
    has_required_checks=True,
    mergeable=True,
    behind_by=0,
    rebase_requested=False,
)
NOTHING = Decision(Kind.NOTHING)


def test_managed_labels() -> None:
    assert {"major-ready", "major-broken", "update-broken"} == MANAGED_LABELS


@pytest.mark.parametrize("update_type", [UpdateType.PATCH, UpdateType.MINOR])
def test_green_up_to_date_minor_or_patch_merges(update_type: UpdateType) -> None:
    assert decide(replace(MERGEABLE, update_type=update_type)) == Decision(Kind.MERGE)


@pytest.mark.parametrize("change", [{"authored_by_dependabot": False}, {"open": False}])
def test_not_dependabot_or_not_open_does_nothing(change: dict[str, bool]) -> None:
    assert decide(replace(MERGEABLE, **change)) == NOTHING
    assert decide(replace(MERGEABLE, update_type=UpdateType.MAJOR, **change)) == NOTHING


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


def test_behind_requests_rebase() -> None:
    assert decide(replace(MERGEABLE, behind_by=2)) == Decision(Kind.REQUEST_REBASE)


def test_behind_with_rebase_already_requested_does_nothing() -> None:
    assert decide(replace(MERGEABLE, behind_by=2, rebase_requested=True)) == NOTHING


@given(
    st.builds(
        Facts,
        authored_by_dependabot=st.booleans(),
        open=st.booleans(),
        update_type=st.sampled_from(UpdateType),
        verdict=st.sampled_from(Verdict),
        has_required_checks=st.booleans(),
        mergeable=st.none() | st.booleans(),
        behind_by=st.integers(min_value=0, max_value=50),
        rebase_requested=st.booleans(),
    )
)
def test_merge_only_for_green_dependabot_minor_or_patch_with_required_checks(
    facts: Facts,
) -> None:
    if decide(facts).kind is Kind.MERGE:
        assert facts.update_type is not UpdateType.MAJOR
        assert facts.verdict is Verdict.GREEN
        assert facts.authored_by_dependabot
        assert facts.open
        assert facts.has_required_checks
        assert facts.mergeable is True
        assert facts.behind_by == 0
