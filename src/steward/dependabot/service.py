from collections.abc import Awaitable, Callable

from steward.dependabot.decision import MANAGED_LABELS, Decision, Facts, Kind, decide
from steward.dependabot.ports import DependabotGitHub, RebaseMemory
from steward.dependabot.update_type import UpdateType, classify
from steward.dependabot.verdict import ci_verdict
from steward.github.models import PullRequest, RepoRef

DEPENDABOT_LOGIN = "dependabot[bot]"
REBASE_COMMENT = "@dependabot rebase"
_MERGEABLE_REREADS = 3
_REREAD_DELAY_SECONDS = 1.0


class DependabotService:
    def __init__(
        self,
        github: DependabotGitHub,
        memory: RebaseMemory,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._github = github
        self._memory = memory
        self._sleep = sleep

    async def evaluate(self, repo: RepoRef, number: int) -> Decision:
        pr = await self._read_pull_request(repo, number)
        if pr.author != DEPENDABOT_LOGIN:
            return Decision(Kind.NOTHING)
        decision = decide(await self._facts(repo, pr))
        await self._apply(repo, pr, decision)
        return decision

    async def _read_pull_request(self, repo: RepoRef, number: int) -> PullRequest:
        # GitHub computes `mergeable` in the background; the first read often has none yet.
        pr = await self._github.pull_request(repo, number)
        for _ in range(_MERGEABLE_REREADS):
            if pr.state != "open" or pr.mergeable is not None:
                break
            await self._sleep(_REREAD_DELAY_SECONDS)
            pr = await self._github.pull_request(repo, number)
        return pr

    async def _facts(self, repo: RepoRef, pr: PullRequest) -> Facts:
        commits = await self._github.pull_request_commits(repo, pr.number)
        required = await self._github.required_checks(repo, pr.base_ref)
        results = await self._github.check_results(repo, pr.head_sha)
        return Facts(
            authored_by_dependabot=bool(commits)
            and all(commit.author == DEPENDABOT_LOGIN for commit in commits),
            open=pr.state == "open" and not pr.draft,
            update_type=classify(commits[0].message) if commits else UpdateType.MAJOR,
            verdict=ci_verdict(results, required),
            has_required_checks=bool(required),
            mergeable=pr.mergeable,
            behind_by=await self._github.behind_by(repo, pr.base_ref, pr.head_sha),
            rebase_requested=await self._memory.was_requested(repo, pr.number, pr.head_sha),
        )

    async def _apply(self, repo: RepoRef, pr: PullRequest, decision: Decision) -> None:
        if decision.kind is Kind.LABEL and decision.label is not None:
            if decision.label not in pr.labels:
                await self._github.add_label(repo, pr.number, decision.label)
            await self._remove_managed_labels(repo, pr, keep=decision.label)
        elif decision.kind is Kind.MERGE:
            await self._remove_managed_labels(repo, pr, keep=None)
            await self._github.approve(repo, pr.number, pr.head_sha)
            method = await self._github.merge_method(repo)
            merged = await self._github.merge(repo, pr.number, pr.head_sha, method)
            print(f"{repo.full_name}#{pr.number}: merge {'done' if merged else 'refused'}")
        elif decision.kind is Kind.REQUEST_REBASE:
            await self._github.comment(repo, pr.number, REBASE_COMMENT)
            await self._memory.remember(repo, pr.number, pr.head_sha)

    async def _remove_managed_labels(
        self, repo: RepoRef, pr: PullRequest, keep: str | None
    ) -> None:
        for label in sorted((pr.labels & MANAGED_LABELS) - {keep}):
            await self._github.remove_label(repo, pr.number, label)
