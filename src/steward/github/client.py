from http import HTTPStatus
from typing import Any
from urllib.parse import quote

from steward.github.api import GitHubApi
from steward.github.models import (
    CheckResult,
    CheckState,
    Commit,
    MergeMethod,
    PullRequest,
    RepoRef,
)

# A Dependabot pull request has far fewer than 100 commits or checks, so one page is enough.
_PAGE = "?per_page=100"
_PASSING_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})
_STATUS_STATES = {
    "success": CheckState.SUCCESS,
    "pending": CheckState.PENDING,
    "failure": CheckState.FAILURE,
    "error": CheckState.FAILURE,
}


def _check_run_state(run: dict[str, Any]) -> CheckState:
    if run["status"] != "completed":
        return CheckState.PENDING
    return CheckState.SUCCESS if run["conclusion"] in _PASSING_CONCLUSIONS else CheckState.FAILURE


class GitHubClient:
    def __init__(self, api: GitHubApi) -> None:
        self._api = api

    async def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        accept: frozenset[int] = frozenset({HTTPStatus.OK}),
    ) -> tuple[int, Any]:
        return await self._api.call(method, path, body, accept)

    async def _get(self, path: str) -> Any:
        return await self._api.get(path)

    async def pull_request(self, repo: RepoRef, number: int) -> PullRequest:
        data = await self._get(f"/repos/{repo.full_name}/pulls/{number}")
        return PullRequest(
            number=data["number"],
            state=data["state"],
            draft=data["draft"],
            author=data["user"]["login"],
            head_sha=data["head"]["sha"],
            base_ref=data["base"]["ref"],
            mergeable=data["mergeable"],
            labels=frozenset(label["name"] for label in data["labels"]),
        )

    async def open_dependabot_prs(self, repo: RepoRef) -> list[int]:
        pulls = await self._get(f"/repos/{repo.full_name}/pulls?state=open&per_page=100")
        return [pull["number"] for pull in pulls if pull["user"]["login"] == "dependabot[bot]"]

    async def pull_request_commits(self, repo: RepoRef, number: int) -> list[Commit]:
        data = await self._get(f"/repos/{repo.full_name}/pulls/{number}/commits{_PAGE}")
        return [
            Commit(item["author"]["login"] if item["author"] else None, item["commit"]["message"])
            for item in data
        ]

    async def required_checks(self, repo: RepoRef, branch: str) -> frozenset[str]:
        # Repositories may protect a branch with rulesets, classic protection, or both.
        rules = await self._get(f"/repos/{repo.full_name}/rules/branches/{quote(branch)}")
        names = {
            check["context"]
            for rule in rules
            if rule["type"] == "required_status_checks"
            for check in rule["parameters"]["required_status_checks"]
        }
        status, classic = await self._call(
            "GET",
            f"/repos/{repo.full_name}/branches/{quote(branch)}/protection/required_status_checks",
            accept=frozenset({HTTPStatus.OK, HTTPStatus.NOT_FOUND}),
        )
        if status == HTTPStatus.OK:
            names |= set(classic.get("contexts", []))
            names |= {check["context"] for check in classic.get("checks", [])}
        return frozenset(names)

    async def check_results(self, repo: RepoRef, sha: str) -> list[CheckResult]:
        runs = await self._get(f"/repos/{repo.full_name}/commits/{sha}/check-runs{_PAGE}")
        statuses = await self._get(f"/repos/{repo.full_name}/commits/{sha}/status{_PAGE}")
        return [CheckResult(run["name"], _check_run_state(run)) for run in runs["check_runs"]] + [
            CheckResult(status["context"], _STATUS_STATES.get(status["state"], CheckState.FAILURE))
            for status in statuses["statuses"]
        ]

    async def behind_by(self, repo: RepoRef, base_ref: str, head_sha: str) -> int:
        data = await self._get(f"/repos/{repo.full_name}/compare/{quote(base_ref)}...{head_sha}")
        return int(data["behind_by"])

    async def merge_method(self, repo: RepoRef) -> MergeMethod:
        data = await self._get(f"/repos/{repo.full_name}")
        if data.get("allow_squash_merge", True):
            return "squash"
        if data.get("allow_merge_commit", True):
            return "merge"
        return "rebase"

    async def approve(self, repo: RepoRef, number: int, sha: str) -> None:
        await self._call(
            "POST",
            f"/repos/{repo.full_name}/pulls/{number}/reviews",
            {"commit_id": sha, "event": "APPROVE"},
        )

    async def merge(self, repo: RepoRef, number: int, sha: str, method: MergeMethod) -> bool:
        # 405: not mergeable now; 409: the head moved since `sha`. Both mean "not this time".
        status, _ = await self._call(
            "PUT",
            f"/repos/{repo.full_name}/pulls/{number}/merge",
            {"sha": sha, "merge_method": method},
            accept=frozenset({HTTPStatus.OK, HTTPStatus.METHOD_NOT_ALLOWED, HTTPStatus.CONFLICT}),
        )
        return status == HTTPStatus.OK

    async def add_label(self, repo: RepoRef, number: int, label: str) -> None:
        await self._call(
            "POST", f"/repos/{repo.full_name}/issues/{number}/labels", {"labels": [label]}
        )

    async def remove_label(self, repo: RepoRef, number: int, label: str) -> None:
        await self._call(
            "DELETE",
            f"/repos/{repo.full_name}/issues/{number}/labels/{quote(label, safe='')}",
            accept=frozenset({HTTPStatus.OK, HTTPStatus.NOT_FOUND}),
        )

    async def update_branch(self, repo: RepoRef, number: int, expected_head_sha: str) -> bool:
        # 422: the head moved since it was evaluated, or main cannot be merged in cleanly.
        status, _ = await self._call(
            "PUT",
            f"/repos/{repo.full_name}/pulls/{number}/update-branch",
            {"expected_head_sha": expected_head_sha},
            accept=frozenset({HTTPStatus.ACCEPTED, HTTPStatus.UNPROCESSABLE_ENTITY}),
        )
        return status == HTTPStatus.ACCEPTED
