from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from steward.github.models import CheckResult, CheckState, Commit, MergeMethod, PullRequest, RepoRef

REPO = RepoRef("Isma-L154", "nextsode")
DEPENDABOT = "dependabot[bot]"


def dependabot_pr(**changes: Any) -> PullRequest:
    pr = PullRequest(
        number=7,
        state="open",
        draft=False,
        author=DEPENDABOT,
        head_sha="abc",
        base_ref="main",
        mergeable=True,
        labels=frozenset(),
    )
    return replace(pr, **changes)


def _commit(update_type: str) -> Commit:
    message = (
        "Bump httpx from 0.27.0 to 0.28.1\n\n---\nupdated-dependencies:\n"
        "- dependency-name: httpx\n  dependency-version: 0.28.1\n"
        f"  update-type: version-update:semver-{update_type}\n...\n"
    )
    return Commit(author=DEPENDABOT, message=message)


def minor_commit() -> Commit:
    return _commit("minor")


def major_commit() -> Commit:
    return _commit("major")


def success(name: str) -> CheckResult:
    return CheckResult(name, CheckState.SUCCESS)


def failure(name: str) -> CheckResult:
    return CheckResult(name, CheckState.FAILURE)


@dataclass
class FakeGitHub:
    pr: PullRequest = field(default_factory=dependabot_pr)
    commits: Sequence[Commit] = field(default_factory=lambda: [minor_commit()])
    required: frozenset[str] = frozenset({"test"})
    checks: Sequence[CheckResult] = field(default_factory=lambda: [success("test")])
    behind: int = 0
    method: MergeMethod = "squash"
    merge_succeeds: bool = True
    # Successive values of `mergeable` on each read; the last one repeats.
    mergeable_sequence: Sequence[bool | None] = ()
    writes: list[tuple[Any, ...]] = field(default_factory=list)
    pull_request_reads: int = 0

    async def pull_request(self, repo: RepoRef, number: int) -> PullRequest:
        self.pull_request_reads += 1
        if not self.mergeable_sequence:
            return self.pr
        index = min(self.pull_request_reads, len(self.mergeable_sequence)) - 1
        return replace(self.pr, mergeable=self.mergeable_sequence[index])

    async def pull_request_commits(self, repo: RepoRef, number: int) -> list[Commit]:
        return list(self.commits)

    async def required_checks(self, repo: RepoRef, branch: str) -> frozenset[str]:
        return self.required

    async def check_results(self, repo: RepoRef, sha: str) -> list[CheckResult]:
        return list(self.checks)

    async def behind_by(self, repo: RepoRef, base_ref: str, head_sha: str) -> int:
        return self.behind

    async def merge_method(self, repo: RepoRef) -> MergeMethod:
        return self.method

    async def approve(self, repo: RepoRef, number: int, sha: str) -> None:
        self.writes.append(("approve", number, sha))

    async def merge(self, repo: RepoRef, number: int, sha: str, method: MergeMethod) -> bool:
        self.writes.append(("merge", number, sha, method))
        return self.merge_succeeds

    async def add_label(self, repo: RepoRef, number: int, label: str) -> None:
        self.writes.append(("add_label", number, label))

    async def remove_label(self, repo: RepoRef, number: int, label: str) -> None:
        self.writes.append(("remove_label", number, label))

    async def comment(self, repo: RepoRef, number: int, body: str) -> None:
        self.writes.append(("comment", number, body))


@dataclass
class FakeMemory:
    requested: set[tuple[str, int, str]] = field(default_factory=set)

    async def was_requested(self, repo: RepoRef, number: int, head_sha: str) -> bool:
        return (repo.full_name, number, head_sha) in self.requested

    async def remember(self, repo: RepoRef, number: int, head_sha: str) -> None:
        self.requested.add((repo.full_name, number, head_sha))


async def no_sleep(seconds: float) -> None:
    return None
