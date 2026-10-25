from steward.standards.snapshot import CommitInfo, Finding, RepoSnapshot


def is_bot(login: str | None, email: str) -> bool:
    return (login or "").endswith("[bot]") or email.endswith("[bot]@users.noreply.github.com")


def commit_link(snapshot: RepoSnapshot, commit: CommitInfo) -> str:
    return f"[{commit.oid[:7]}](https://github.com/{snapshot.repo.full_name}/commit/{commit.oid})"


def check_no_direct_push(snapshot: RepoSnapshot) -> list[Finding]:
    # A repository's first commit is created with the repository, not pushed past a PR.
    return [
        Finding(
            "direct-push",
            f"Commit {commit_link(snapshot, commit)} went straight to `{snapshot.default_branch}`",
        )
        for commit in snapshot.commits
        if not commit.from_merged_pr and not commit.is_root
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
