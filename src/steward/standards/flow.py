from steward.standards.snapshot import CommitInfo, Finding, MergedPr, RepoSnapshot


def is_bot(login: str | None, email: str) -> bool:
    return (login or "").endswith("[bot]") or email.endswith("[bot]@users.noreply.github.com")


def commit_link(snapshot: RepoSnapshot, commit: CommitInfo) -> str:
    return f"[{commit.oid[:7]}](https://github.com/{snapshot.repo.full_name}/commit/{commit.oid})"


def pr_link(snapshot: RepoSnapshot, pr: MergedPr) -> str:
    return f"[#{pr.number}](https://github.com/{snapshot.repo.full_name}/pull/{pr.number})"


def check_no_direct_push(snapshot: RepoSnapshot) -> list[Finding]:
    # A repository's first commit is created with the repository, not pushed past a PR.
    return [
        Finding(
            "direct-push", f"Commit {commit_link(snapshot, commit)} reached `main` without a PR"
        )
        for commit in snapshot.commits
        if not commit.from_merged_pr and not commit.is_root
    ]


def check_prs_reference_issues(
    snapshot: RepoSnapshot, trusted_bots: frozenset[str]
) -> list[Finding]:
    return [
        Finding("pr-issue", f"Pull request {pr_link(snapshot, pr)} does not close an issue")
        for pr in snapshot.merged_prs
        if not pr.references_issue and pr.author_login not in trusted_bots
    ]


def check_commit_identity(snapshot: RepoSnapshot, owner_email: str) -> list[Finding]:
    return [
        Finding(
            "commit-identity",
            f"Commit {commit_link(snapshot, commit)} is authored with another email",
        )
        for commit in snapshot.commits
        if not is_bot(commit.author_login, commit.author_email)
        and commit.author_email.lower() != owner_email.lower()
    ]
