from steward.standards.flow import (
    check_commit_identity,
    check_no_direct_push,
    check_prs_reference_issues,
    is_bot,
)
from tests.standards.builders import OWNER_EMAIL, commit, merged_pr, snapshot

TRUSTED = frozenset({"dependabot", "dependabot[bot]", "app-steward", "app-steward[bot]"})


def test_compliant_history_has_no_findings() -> None:
    assert check_no_direct_push(snapshot()) == []
    assert check_prs_reference_issues(snapshot(), TRUSTED) == []
    assert check_commit_identity(snapshot(), OWNER_EMAIL) == []


def test_commit_not_from_a_merged_pr_is_a_direct_push() -> None:
    findings = check_no_direct_push(snapshot(commits=[commit(from_merged_pr=False)]))
    assert [f.rule for f in findings] == ["direct-push"]
    assert "commit/a1b2c3d4e5f60718293a4b5c6d7e8f9012345678" in findings[0].detail


def test_feature_branch_commit_brought_in_by_a_merge_is_not_a_direct_push() -> None:
    history = [commit(oid="b" * 40, from_merged_pr=True), commit(message="Merge pull request #3")]
    assert check_no_direct_push(snapshot(commits=history)) == []


def test_initial_commit_is_not_a_direct_push() -> None:
    initial = commit(is_root=True, from_merged_pr=False, message="Initial commit")
    assert check_no_direct_push(snapshot(commits=[initial])) == []


def test_merged_pr_without_an_issue_is_reported() -> None:
    findings = check_prs_reference_issues(
        snapshot(merged_prs=[merged_pr(references_issue=False)]), TRUSTED
    )
    assert [f.rule for f in findings] == ["pr-issue"]
    assert "pull/12" in findings[0].detail


def test_dependabot_and_steward_prs_need_no_issue() -> None:
    prs = [merged_pr(author_login=login, references_issue=False) for login in TRUSTED]
    assert check_prs_reference_issues(snapshot(merged_prs=prs), TRUSTED) == []


def test_human_commit_with_another_email_is_reported() -> None:
    findings = check_commit_identity(
        snapshot(commits=[commit(author_email="someone@example.com")]), OWNER_EMAIL
    )
    assert [f.rule for f in findings] == ["commit-identity"]
    assert "someone@example.com" not in findings[0].detail


def test_bot_commits_are_not_identity_checked() -> None:
    bot = commit(
        author_email="49699333+dependabot[bot]@users.noreply.github.com", author_login=None
    )
    assert check_commit_identity(snapshot(commits=[bot]), OWNER_EMAIL) == []


def test_is_bot() -> None:
    assert is_bot("app-steward[bot]", "x@example.com")
    assert is_bot(None, "49699333+dependabot[bot]@users.noreply.github.com")
    assert not is_bot("Isma-L154", OWNER_EMAIL)


def test_direct_push_names_the_real_default_branch() -> None:
    findings = check_no_direct_push(
        snapshot(default_branch="master", commits=[commit(from_merged_pr=False)])
    )
    assert "`master`" in findings[0].detail
