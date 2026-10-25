from steward.standards.flow import check_commit_identity, check_no_direct_push, is_bot
from tests.standards.builders import OWNER_EMAIL, commit, snapshot


def test_compliant_history_has_no_findings() -> None:
    assert check_no_direct_push(snapshot()) == []
    assert check_commit_identity(snapshot(), OWNER_EMAIL) == []


def test_commit_not_from_a_merged_pr_is_a_direct_push() -> None:
    findings = check_no_direct_push(snapshot(commits=[commit(from_merged_pr=False)]))
    assert [f.rule for f in findings] == ["direct-push"]
    assert "commit/a1b2c3d4e5f60718293a4b5c6d7e8f9012345678" in findings[0].detail


def test_feature_branch_commit_brought_in_by_a_merge_is_not_a_direct_push() -> None:
    history = [commit(oid="b" * 40, from_merged_pr=True), commit()]
    assert check_no_direct_push(snapshot(commits=history)) == []


def test_initial_commit_is_not_a_direct_push() -> None:
    initial = commit(is_root=True, from_merged_pr=False)
    assert check_no_direct_push(snapshot(commits=[initial])) == []


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
