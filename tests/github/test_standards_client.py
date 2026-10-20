from datetime import UTC, datetime
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from steward.github.api import GitHubApi
from steward.github.app_auth import InstallationTokens
from steward.github.client import GitHubClient
from steward.github.models import RepoRef, TrackingIssue
from steward.github.standards_client import StandardsClient
from steward.standards.flow import check_no_direct_push
from steward.standards.snapshot import CommitInfo, MergedPr
from tests.github.fake_http import FakeHttp
from tests.github.signer import CryptographySigner

REPO = RepoRef("Isma-L154", "nextsode")
BASE = "/repos/Isma-L154/nextsode"
SINCE = datetime(2026, 9, 18, tzinfo=UTC)
BOT_EMAIL = "49699333+dependabot[bot]@users.noreply.github.com"


def _commit(oid: str, message: str, *, kind: str = "human") -> Any:
    email, login, merged = {
        "human": ("ismaleonsaenz@gmail.com", "Isma-L154", True),
        # Pushed seconds ago: GitHub has not linked it to its pull request yet.
        "unlinked": ("ismaleonsaenz@gmail.com", "Isma-L154", False),
        "bot": (BOT_EMAIL, None, False),
        "root": ("x@example.com", None, False),
    }[kind]
    return {
        "oid": oid,
        "message": message,
        "parents": {"totalCount": 0 if kind == "root" else 1},
        "author": {"email": email, "user": None if login is None else {"login": login}},
        "associatedPullRequests": {"nodes": [{"merged": True}] if merged else []},
    }


def _pr(number: int, base: str, merged_at: str, author: str | None, closes: int) -> Any:
    return {
        "number": number,
        "title": f"PR {number}",
        "body": "Closes #2" if closes else "",
        "headRefName": f"feature/{number}",
        "baseRefName": base,
        "mergedAt": merged_at,
        "author": None if author is None else {"login": author},
        "closingIssuesReferences": {"totalCount": closes},
        "mergeCommit": None,
        "commits": {"nodes": []},
    }


def _landed(number: int, base: str, merge_commit: str, *commits: str) -> Any:
    """A pull request merged moments ago, with the commits it brought."""
    return {
        **_pr(number, base, "2026-10-20T01:58:00Z", "Isma-L154", 1),
        "mergeCommit": {"oid": merge_commit},
        "commits": {"nodes": [{"commit": {"oid": oid}} for oid in commits]},
    }


def _repository(**changes: Any) -> dict[str, Any]:
    repository: dict[str, Any] = {
        "defaultBranchRef": {
            "name": "main",
            "target": {
                "history": {
                    "nodes": [
                        _commit("a" * 40, "feat: x"),
                        _commit("b" * 40, "Bump x", kind="bot"),
                        _commit("c" * 40, "Initial commit", kind="root"),
                    ]
                }
            },
        },
        "readme": {"text": "# Readme"},
        "agents": None,
        "dependabot": {"text": "version: 2"},
        "workflows": {
            "entries": [
                {"name": "ci.yml", "object": {"text": "on: pull_request"}},
                {"name": "notes.txt", "object": {"text": "ignore me"}},
                {"name": "sub", "object": {}},
            ]
        },
        "pullRequests": {
            "nodes": [
                _pr(3, "main", "2026-10-01T10:00:00Z", "Isma-L154", 1),
                _pr(1, "main", "2026-08-01T10:00:00Z", "Isma-L154", 0),
                _pr(4, "dev", "2026-10-02T10:00:00Z", None, 0),
            ]
        },
    }
    repository.update(changes)
    return repository


@pytest.fixture
def http() -> FakeHttp:
    fake = FakeHttp()
    fake.on(
        "POST",
        "/app/installations/42/access_tokens",
        201,
        {"token": "ghs_x", "expires_at": "2099-01-01T00:00:00Z"},
    )
    fake.on("GET", f"{BASE}/rules/branches/main", body=[])
    fake.on(
        "GET",
        f"{BASE}/branches/main/protection/required_status_checks",
        body={"contexts": ["test"], "checks": []},
    )
    fake.on(
        "GET",
        f"{BASE}/git/trees/main",
        body={
            "tree": [
                {"path": "package.json", "type": "blob"},
                {"path": "src", "type": "tree"},
                {"path": "src/app.ts", "type": "blob"},
            ],
            "truncated": False,
        },
    )
    return fake


@pytest.fixture
def client(http: FakeHttp, rsa_key: RSAPrivateKey) -> StandardsClient:
    tokens = InstallationTokens(http, "123", CryptographySigner(rsa_key), lambda: 0.0)
    api = GitHubApi(http, tokens, 42)
    return StandardsClient(api, GitHubClient(api))


async def test_snapshot_maps_the_repository(http: FakeHttp, client: StandardsClient) -> None:
    http.on("POST", "/graphql", body={"data": {"repository": _repository()}})
    snapshot = await client.snapshot(REPO, SINCE)
    assert snapshot is not None
    assert snapshot.default_branch == "main"
    assert snapshot.readme == "# Readme"
    assert snapshot.agents is None
    assert snapshot.dependabot == "version: 2"
    assert dict(snapshot.workflows) == {"ci.yml": "on: pull_request"}
    assert snapshot.paths == {"package.json", "src/app.ts"}
    assert snapshot.required_checks == {"test"}
    assert list(snapshot.commits) == [
        CommitInfo("a" * 40, "feat: x", "ismaleonsaenz@gmail.com", "Isma-L154", False, True),
        CommitInfo("b" * 40, "Bump x", BOT_EMAIL, None, False, False),
        CommitInfo("c" * 40, "Initial commit", "x@example.com", None, True, False),
    ]
    assert list(snapshot.merged_prs) == [
        MergedPr(3, "PR 3", "Closes #2", "feature/3", "Isma-L154", True)
    ]


async def test_snapshot_sends_the_window_start(http: FakeHttp, client: StandardsClient) -> None:
    http.on("POST", "/graphql", body={"data": {"repository": _repository()}})
    await client.snapshot(REPO, SINCE)
    sent = next(r for r in http.requests if r.path == "/graphql").json()
    assert sent["variables"] == {
        "owner": "Isma-L154",
        "name": "nextsode",
        "since": "2026-09-18T00:00:00+00:00",
    }


def _history(*commits: Any) -> dict[str, Any]:
    return {"name": "main", "target": {"history": {"nodes": list(commits)}}}


async def test_just_merged_pull_request_vouches_for_its_unlinked_commits(
    http: FakeHttp, client: StandardsClient
) -> None:
    merge, work = "d" * 40, "e" * 40
    repository = _repository(
        defaultBranchRef=_history(
            _commit(merge, "Merge pull request #5", kind="unlinked"),
            _commit(work, "fix: y", kind="unlinked"),
        ),
        pullRequests={
            "nodes": [
                _landed(5, "main", merge, work),
            ]
        },
    )
    http.on("POST", "/graphql", body={"data": {"repository": repository}})
    snapshot = await client.snapshot(REPO, SINCE)
    assert snapshot is not None
    assert [commit.from_merged_pr for commit in snapshot.commits] == [True, True]
    assert check_no_direct_push(snapshot) == []


async def test_unlinked_commit_outside_every_pull_request_is_a_direct_push(
    http: FakeHttp, client: StandardsClient
) -> None:
    repository = _repository(
        defaultBranchRef=_history(_commit("f" * 40, "fix: z", kind="unlinked")),
        pullRequests={
            "nodes": [
                _landed(5, "main", "d" * 40, "e" * 40),
                # A pull request into another branch says nothing about main.
                _landed(6, "dev", "1" * 40, "f" * 40),
            ]
        },
    )
    http.on("POST", "/graphql", body={"data": {"repository": repository}})
    snapshot = await client.snapshot(REPO, SINCE)
    assert snapshot is not None
    assert [finding.rule for finding in check_no_direct_push(snapshot)] == ["direct-push"]


async def test_empty_repository_has_no_snapshot(http: FakeHttp, client: StandardsClient) -> None:
    http.on("POST", "/graphql", body={"data": {"repository": _repository(defaultBranchRef=None)}})
    assert await client.snapshot(REPO, SINCE) is None


async def test_tracking_issue_skips_pull_requests(http: FakeHttp, client: StandardsClient) -> None:
    http.on(
        "GET",
        f"{BASE}/issues",
        body=[
            {"number": 9, "state": "open", "body": "x", "pull_request": {}},
            {"number": 7, "state": "closed", "body": None},
        ],
    )
    assert await client.tracking_issue(REPO, "app-steward[bot]") == TrackingIssue(7, "closed", "")


async def test_no_tracking_issue(http: FakeHttp, client: StandardsClient) -> None:
    http.on("GET", f"{BASE}/issues", body=[])
    assert await client.tracking_issue(REPO, "app-steward[bot]") is None


async def test_create_issue(http: FakeHttp, client: StandardsClient) -> None:
    http.on("POST", f"{BASE}/issues", 201, {"number": 10})
    await client.create_issue(REPO, "Repository standards", "body", "standards")
    sent = next(r for r in http.requests if r.path == f"{BASE}/issues").json()
    assert sent == {"title": "Repository standards", "body": "body", "labels": ["standards"]}


async def test_closing_an_issue_marks_it_completed(http: FakeHttp, client: StandardsClient) -> None:
    http.on("PATCH", f"{BASE}/issues/7", body={"number": 7})
    await client.update_issue(REPO, 7, "all good", "closed")
    sent = next(r for r in http.requests if r.path == f"{BASE}/issues/7").json()
    assert sent == {"body": "all good", "state": "closed", "state_reason": "completed"}


async def test_reopening_sends_no_state_reason(http: FakeHttp, client: StandardsClient) -> None:
    http.on("PATCH", f"{BASE}/issues/7", body={"number": 7})
    await client.update_issue(REPO, 7, "broken again", "open")
    sent = next(r for r in http.requests if r.path == f"{BASE}/issues/7").json()
    assert sent == {"body": "broken again", "state": "open"}
