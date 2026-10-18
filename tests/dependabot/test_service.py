from steward.dependabot.decision import Decision, Kind
from steward.dependabot.service import DependabotService
from steward.github.models import BranchUpdate, Commit
from tests.dependabot.fakes import (
    REPO,
    STEWARD,
    FakeGitHub,
    FakeMemory,
    dependabot_pr,
    failure,
    major_commit,
    minor_commit,
    no_sleep,
    success,
)


def _service(github: FakeGitHub, memory: FakeMemory | None = None) -> DependabotService:
    return DependabotService(github, memory or FakeMemory(), no_sleep, STEWARD)


async def test_green_minor_is_approved_then_merged_with_the_head_sha() -> None:
    github = FakeGitHub()
    decision = await _service(github).evaluate(REPO, 7)
    assert decision == Decision(Kind.MERGE)
    assert github.writes == [("approve", 7, "abc"), ("merge", 7, "abc", "squash")]


async def test_merge_uses_the_repository_merge_method() -> None:
    github = FakeGitHub(method="rebase")
    await _service(github).evaluate(REPO, 7)
    assert github.writes[-1] == ("merge", 7, "abc", "rebase")


async def test_extra_commit_by_someone_else_blocks_everything() -> None:
    github = FakeGitHub(commits=[minor_commit(), Commit(author="Isma-L154", message="tweak")])
    assert (await _service(github).evaluate(REPO, 7)).kind is Kind.NOTHING
    assert github.writes == []


async def test_commit_without_github_author_blocks_everything() -> None:
    github = FakeGitHub(commits=[minor_commit(), Commit(author=None, message="tweak")])
    assert (await _service(github).evaluate(REPO, 7)).kind is Kind.NOTHING
    assert github.writes == []


async def test_pr_not_opened_by_dependabot_does_nothing() -> None:
    github = FakeGitHub(pr=dependabot_pr(author="Isma-L154"))
    assert (await _service(github).evaluate(REPO, 7)).kind is Kind.NOTHING
    assert github.writes == []


async def test_draft_pr_does_nothing() -> None:
    github = FakeGitHub(pr=dependabot_pr(draft=True))
    assert (await _service(github).evaluate(REPO, 7)).kind is Kind.NOTHING
    assert github.writes == []


async def test_merge_clears_a_stale_update_broken_label() -> None:
    github = FakeGitHub(pr=dependabot_pr(labels=frozenset({"update-broken", "dependencies"})))
    await _service(github).evaluate(REPO, 7)
    assert github.writes == [
        ("remove_label", 7, "update-broken"),
        ("approve", 7, "abc"),
        ("merge", 7, "abc", "squash"),
    ]


async def test_major_green_gets_major_ready_and_loses_major_broken() -> None:
    github = FakeGitHub(
        pr=dependabot_pr(labels=frozenset({"major-broken"})), commits=[major_commit()]
    )
    assert await _service(github).evaluate(REPO, 7) == Decision(Kind.LABEL, "major-ready")
    assert github.writes == [("add_label", 7, "major-ready"), ("remove_label", 7, "major-broken")]


async def test_major_is_never_merged_even_when_green() -> None:
    github = FakeGitHub(commits=[major_commit()])
    await _service(github).evaluate(REPO, 7)
    assert all(write[0] not in {"approve", "merge"} for write in github.writes)


async def test_red_minor_gets_update_broken() -> None:
    github = FakeGitHub(checks=[failure("test")])
    assert await _service(github).evaluate(REPO, 7) == Decision(Kind.LABEL, "update-broken")
    assert github.writes == [("add_label", 7, "update-broken")]


async def test_label_already_present_is_not_added_again() -> None:
    github = FakeGitHub(
        pr=dependabot_pr(labels=frozenset({"major-ready"})), commits=[major_commit()]
    )
    await _service(github).evaluate(REPO, 7)
    assert github.writes == []


async def test_behind_updates_the_branch_once_per_head_sha() -> None:
    github = FakeGitHub(behind=3)
    memory = FakeMemory()
    assert (await _service(github, memory).evaluate(REPO, 7)).kind is Kind.UPDATE_BRANCH
    assert (await _service(github, memory).evaluate(REPO, 7)).kind is Kind.NOTHING
    assert github.writes == [("update_branch", 7, "abc")]


async def test_new_head_after_an_update_can_be_updated_again() -> None:
    memory = FakeMemory()
    await _service(FakeGitHub(behind=3), memory).evaluate(REPO, 7)
    github = FakeGitHub(pr=dependabot_pr(head_sha="def"), behind=1)
    assert (await _service(github, memory).evaluate(REPO, 7)).kind is Kind.UPDATE_BRANCH


async def test_refused_branch_update_is_not_remembered() -> None:
    memory = FakeMemory()
    await _service(FakeGitHub(behind=3, update_result=BranchUpdate.NOT_NOW), memory).evaluate(
        REPO, 7
    )
    github = FakeGitHub(behind=3)
    assert (await _service(github, memory).evaluate(REPO, 7)).kind is Kind.UPDATE_BRANCH


async def test_stewards_own_branch_update_commit_does_not_block_the_merge() -> None:
    github = FakeGitHub(commits=[minor_commit(), Commit(author=STEWARD, message="Merge main")])
    assert (await _service(github).evaluate(REPO, 7)).kind is Kind.MERGE


async def test_already_merged_pr_does_nothing() -> None:
    github = FakeGitHub(pr=dependabot_pr(state="closed", mergeable=None))
    assert (await _service(github).evaluate(REPO, 7)).kind is Kind.NOTHING
    assert github.writes == []


async def test_unknown_mergeable_is_reread_three_times_then_nothing() -> None:
    github = FakeGitHub(mergeable_sequence=[None, None, None, None])
    assert (await _service(github).evaluate(REPO, 7)).kind is Kind.NOTHING
    assert github.pull_request_reads == 4
    assert github.writes == []


async def test_mergeable_resolving_on_reread_merges() -> None:
    github = FakeGitHub(mergeable_sequence=[None, True])
    assert (await _service(github).evaluate(REPO, 7)).kind is Kind.MERGE
    assert github.pull_request_reads == 2


async def test_failed_merge_call_is_reported_not_raised() -> None:
    github = FakeGitHub(merge_succeeds=False)
    assert (await _service(github).evaluate(REPO, 7)).kind is Kind.MERGE
    assert github.writes[-1] == ("merge", 7, "abc", "squash")


async def test_no_required_checks_never_merges() -> None:
    github = FakeGitHub(required=frozenset(), checks=[success("test")])
    assert (await _service(github).evaluate(REPO, 7)).kind is Kind.NOTHING
    assert github.writes == []


async def test_open_updates_are_all_evaluated() -> None:
    github = FakeGitHub(open_numbers=[3, 5])
    decisions = await _service(github).evaluate_open(REPO)
    assert github.read_numbers == [3, 5]
    assert [d.kind for d in decisions] == [Kind.MERGE, Kind.MERGE]


async def test_at_most_four_open_updates_are_evaluated_per_push() -> None:
    github = FakeGitHub(open_numbers=[1, 2, 3, 4, 5, 6])
    assert len(await _service(github).evaluate_open(REPO)) == 4
    assert github.read_numbers == [1, 2, 3, 4]


async def test_no_open_updates_evaluates_nothing() -> None:
    github = FakeGitHub(open_numbers=[])
    assert await _service(github).evaluate_open(REPO) == []
    assert github.writes == []


async def test_forbidden_branch_update_labels_the_pr_and_is_not_remembered() -> None:
    memory = FakeMemory()
    github = FakeGitHub(behind=3, update_result=BranchUpdate.FORBIDDEN)
    await _service(github, memory).evaluate(REPO, 7)
    assert github.writes == [("update_branch", 7, "abc"), ("add_label", 7, "update-blocked")]
    assert memory.requested == set()


async def test_forbidden_update_does_not_label_twice() -> None:
    github = FakeGitHub(
        pr=dependabot_pr(labels=frozenset({"update-blocked"})),
        behind=3,
        update_result=BranchUpdate.FORBIDDEN,
    )
    await _service(github).evaluate(REPO, 7)
    assert github.writes == [("update_branch", 7, "abc")]


async def test_merge_clears_update_blocked() -> None:
    github = FakeGitHub(pr=dependabot_pr(labels=frozenset({"update-blocked"})))
    await _service(github).evaluate(REPO, 7)
    assert github.writes[0] == ("remove_label", 7, "update-blocked")
