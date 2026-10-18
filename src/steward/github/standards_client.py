from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Any
from urllib.parse import quote

from steward.github.api import GitHubApi
from steward.github.client import GitHubClient
from steward.github.models import RepoRef
from steward.standards.snapshot import CommitInfo, MergedPr, RepoSnapshot

# One query reads everything the checks need except the tree and the branch rules, so an
# audit stays far below the free plan's 50 subrequests per invocation.
_SNAPSHOT_QUERY = """
query($owner: String!, $name: String!, $since: GitTimestamp!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      name
      target {
        ... on Commit {
          history(first: 100, since: $since) {
            nodes {
              oid
              message
              parents { totalCount }
              author { email user { login } }
              associatedPullRequests(first: 5) { nodes { merged } }
            }
          }
        }
      }
    }
    readme: object(expression: "HEAD:README.md") { ... on Blob { text } }
    agents: object(expression: "HEAD:AGENTS.md") { ... on Blob { text } }
    dependabot: object(expression: "HEAD:.github/dependabot.yml") { ... on Blob { text } }
    workflows: object(expression: "HEAD:.github/workflows") {
      ... on Tree { entries { name object { ... on Blob { text } } } }
    }
    pullRequests(states: MERGED, first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number title body headRefName baseRefName mergedAt
        author { login }
        closingIssuesReferences { totalCount }
      }
    }
  }
}
"""
_WORKFLOW_SUFFIXES = (".yml", ".yaml")


@dataclass(frozen=True)
class InstalledRepo:
    repo: RepoRef
    archived: bool
    topics: tuple[str, ...]


@dataclass(frozen=True)
class TrackingIssue:
    number: int
    state: str
    body: str


def _text(blob: Any) -> str | None:
    return blob.get("text") if isinstance(blob, dict) else None


def _commit(node: dict[str, Any]) -> CommitInfo:
    user = node["author"].get("user")
    return CommitInfo(
        oid=node["oid"],
        message=node["message"],
        author_email=node["author"].get("email") or "",
        author_login=user["login"] if user else None,
        is_root=node["parents"]["totalCount"] == 0,
        from_merged_pr=any(pr["merged"] for pr in node["associatedPullRequests"]["nodes"]),
    )


def _merged_pr(node: dict[str, Any]) -> MergedPr:
    return MergedPr(
        number=node["number"],
        title=node["title"],
        body=node["body"] or "",
        head_ref=node["headRefName"],
        author_login=node["author"]["login"] if node["author"] else "ghost",
        references_issue=node["closingIssuesReferences"]["totalCount"] > 0,
    )


class StandardsClient:
    def __init__(self, api: GitHubApi, dependabot: GitHubClient) -> None:
        self._api = api
        self._dependabot = dependabot

    async def snapshot(self, repo: RepoRef, since: datetime) -> RepoSnapshot | None:
        variables = {"owner": repo.owner, "name": repo.name, "since": since.isoformat()}
        data = (await self._api.graphql(_SNAPSHOT_QUERY, variables))["repository"]
        branch_ref = data["defaultBranchRef"]
        if branch_ref is None:
            return None
        branch = branch_ref["name"]
        workflows = (data["workflows"] or {}).get("entries", [])
        tree = await self._api.get(
            f"/repos/{repo.full_name}/git/trees/{quote(branch, safe='')}?recursive=1"
        )
        return RepoSnapshot(
            repo=repo,
            default_branch=branch,
            readme=_text(data["readme"]),
            agents=_text(data["agents"]),
            dependabot=_text(data["dependabot"]),
            workflows={
                entry["name"]: text
                for entry in workflows
                if entry["name"].endswith(_WORKFLOW_SUFFIXES)
                and (text := _text(entry["object"])) is not None
            },
            paths=frozenset(item["path"] for item in tree["tree"] if item["type"] == "blob"),
            required_checks=await self._dependabot.required_checks(repo, branch),
            commits=[_commit(node) for node in branch_ref["target"]["history"]["nodes"]],
            merged_prs=[
                _merged_pr(node)
                for node in data["pullRequests"]["nodes"]
                if node["baseRefName"] == branch
                and datetime.fromisoformat(node["mergedAt"]) >= since
            ],
        )

    async def installed_repositories(self) -> list[InstalledRepo]:
        # One page: the account has far fewer than 100 repositories.
        data = await self._api.get("/installation/repositories?per_page=100")
        return [
            InstalledRepo(
                RepoRef(item["owner"]["login"], item["name"]),
                archived=bool(item.get("archived")),
                topics=tuple(item.get("topics") or ()),
            )
            for item in data["repositories"]
        ]

    async def tracking_issue(self, repo: RepoRef, creator: str) -> TrackingIssue | None:
        issues = await self._api.get(
            f"/repos/{repo.full_name}/issues?state=all&labels=standards"
            f"&creator={quote(creator)}&per_page=100"
        )
        for issue in issues:
            if "pull_request" not in issue:
                return TrackingIssue(issue["number"], issue["state"], issue["body"] or "")
        return None

    async def create_issue(self, repo: RepoRef, title: str, body: str, label: str) -> None:
        await self._api.call(
            "POST",
            f"/repos/{repo.full_name}/issues",
            {"title": title, "body": body, "labels": [label]},
            accept=frozenset({HTTPStatus.CREATED}),
        )

    async def update_issue(self, repo: RepoRef, number: int, body: str, state: str) -> None:
        payload = {"body": body, "state": state}
        if state == "closed":
            payload["state_reason"] = "completed"
        await self._api.call("PATCH", f"/repos/{repo.full_name}/issues/{number}", payload)
