from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from steward.dependabot.ports import DependabotGitHub
from steward.github.app_auth import InstallationTokens
from steward.github.client import GitHubClient
from steward.github.http import GitHubError
from steward.github.models import CheckResult, CheckState, Commit, PullRequest, RepoRef
from tests.github.fake_http import FakeHttp
from tests.github.signer import CryptographySigner

REPO = RepoRef("Isma-L154", "nextsode")
BASE = "/repos/Isma-L154/nextsode"
FAR_FUTURE = "2099-01-01T00:00:00Z"


@pytest.fixture
def http() -> FakeHttp:
    fake = FakeHttp()
    fake.on(
        "POST",
        "/app/installations/42/access_tokens",
        201,
        {"token": "ghs_x", "expires_at": FAR_FUTURE},
    )
    return fake


@pytest.fixture
def client(http: FakeHttp, rsa_key: RSAPrivateKey) -> GitHubClient:
    return GitHubClient(
        http,
        InstallationTokens(http, "123", CryptographySigner(rsa_key), lambda: 1_792_324_800.0),
        42,
    )


def _api_requests(http: FakeHttp) -> list[Any]:
    return [r for r in http.requests if not r.path.startswith("/app/")]


def test_client_satisfies_the_dependabot_port(client: GitHubClient) -> None:
    port: DependabotGitHub = client
    assert port is client


async def test_every_request_carries_the_api_headers(http: FakeHttp, client: GitHubClient) -> None:
    http.on("GET", f"{BASE}/compare/main...abc", body={"behind_by": 0})
    await client.behind_by(REPO, "main", "abc")
    headers = _api_requests(http)[0].headers
    assert headers["Authorization"] == "Bearer ghs_x"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert headers["User-Agent"] == "steward"


async def test_pull_request_is_mapped(http: FakeHttp, client: GitHubClient) -> None:
    http.on(
        "GET",
        f"{BASE}/pulls/7",
        body={
            "number": 7,
            "state": "open",
            "draft": False,
            "user": {"login": "dependabot[bot]"},
            "head": {"sha": "abc", "ref": "dependabot/uv/x"},
            "base": {"ref": "main"},
            "mergeable": None,
            "labels": [{"name": "dependencies"}, {"name": "major-ready"}],
        },
    )
    assert await client.pull_request(REPO, 7) == PullRequest(
        number=7,
        state="open",
        draft=False,
        author="dependabot[bot]",
        head_sha="abc",
        base_ref="main",
        mergeable=None,
        labels=frozenset({"dependencies", "major-ready"}),
    )


async def test_commits_map_author_login_and_null_author(
    http: FakeHttp, client: GitHubClient
) -> None:
    http.on(
        "GET",
        f"{BASE}/pulls/7/commits",
        body=[
            {"author": {"login": "dependabot[bot]"}, "commit": {"message": "Bump a"}},
            {"author": None, "commit": {"message": "manual"}},
        ],
    )
    assert await client.pull_request_commits(REPO, 7) == [
        Commit("dependabot[bot]", "Bump a"),
        Commit(None, "manual"),
    ]


async def test_required_checks_union_rulesets_and_classic_protection(
    http: FakeHttp, client: GitHubClient
) -> None:
    http.on(
        "GET",
        f"{BASE}/rules/branches/main",
        body=[
            {"type": "deletion"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "lint"}, {"context": "test"}]
                },
            },
        ],
    )
    http.on(
        "GET",
        f"{BASE}/branches/main/protection/required_status_checks",
        body={"contexts": ["semgrep"], "checks": [{"context": "worker", "app_id": 15368}]},
    )
    assert await client.required_checks(REPO, "main") == {"lint", "test", "semgrep", "worker"}


async def test_required_checks_tolerates_404_from_classic_protection(
    http: FakeHttp, client: GitHubClient
) -> None:
    http.on("GET", f"{BASE}/rules/branches/main", body=[])
    http.on(
        "GET",
        f"{BASE}/branches/main/protection/required_status_checks",
        404,
        {"message": "Not Found"},
    )
    assert await client.required_checks(REPO, "main") == frozenset()


async def test_check_runs_and_statuses_map_to_states(http: FakeHttp, client: GitHubClient) -> None:
    def run(name: str, status: str, conclusion: str | None) -> dict[str, Any]:
        return {"name": name, "status": status, "conclusion": conclusion}

    http.on(
        "GET",
        f"{BASE}/commits/abc/check-runs",
        body={
            "check_runs": [
                run("a", "completed", "success"),
                run("b", "completed", "neutral"),
                run("c", "completed", "skipped"),
                run("d", "completed", "failure"),
                run("e", "completed", "cancelled"),
                run("f", "in_progress", None),
                run("g", "queued", None),
            ]
        },
    )
    http.on(
        "GET",
        f"{BASE}/commits/abc/status",
        body={
            "statuses": [
                {"context": "s1", "state": "success"},
                {"context": "s2", "state": "pending"},
                {"context": "s3", "state": "failure"},
                {"context": "s4", "state": "error"},
            ]
        },
    )
    ok, fail, wait = CheckState.SUCCESS, CheckState.FAILURE, CheckState.PENDING
    assert await client.check_results(REPO, "abc") == [
        CheckResult("a", ok),
        CheckResult("b", ok),
        CheckResult("c", ok),
        CheckResult("d", fail),
        CheckResult("e", fail),
        CheckResult("f", wait),
        CheckResult("g", wait),
        CheckResult("s1", ok),
        CheckResult("s2", wait),
        CheckResult("s3", fail),
        CheckResult("s4", fail),
    ]


async def test_behind_by(http: FakeHttp, client: GitHubClient) -> None:
    http.on("GET", f"{BASE}/compare/main...abc", body={"behind_by": 3, "ahead_by": 1})
    assert await client.behind_by(REPO, "main", "abc") == 3


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (
            {"allow_squash_merge": True, "allow_merge_commit": True, "allow_rebase_merge": True},
            "squash",
        ),
        (
            {"allow_squash_merge": False, "allow_merge_commit": True, "allow_rebase_merge": True},
            "merge",
        ),
        (
            {"allow_squash_merge": False, "allow_merge_commit": False, "allow_rebase_merge": True},
            "rebase",
        ),
        ({}, "squash"),
    ],
)
async def test_merge_method_prefers_squash_then_merge_then_rebase(
    http: FakeHttp, client: GitHubClient, flags: dict[str, bool], expected: str
) -> None:
    http.on("GET", BASE, body={"name": "nextsode", **flags})
    assert await client.merge_method(REPO) == expected


async def test_approve_sends_commit_and_event(http: FakeHttp, client: GitHubClient) -> None:
    http.on("POST", f"{BASE}/pulls/7/reviews", body={"id": 1})
    await client.approve(REPO, 7, "abc")
    assert _api_requests(http)[0].json() == {"commit_id": "abc", "event": "APPROVE"}


async def test_merge_sends_sha_and_method(http: FakeHttp, client: GitHubClient) -> None:
    http.on("PUT", f"{BASE}/pulls/7/merge", body={"merged": True})
    assert await client.merge(REPO, 7, "abc", "squash") is True
    assert _api_requests(http)[0].json() == {"sha": "abc", "merge_method": "squash"}


@pytest.mark.parametrize("status", [405, 409])
async def test_merge_returns_false_on_405_and_409(
    http: FakeHttp, client: GitHubClient, status: int
) -> None:
    http.on("PUT", f"{BASE}/pulls/7/merge", status, {"message": "not mergeable"})
    assert await client.merge(REPO, 7, "abc", "squash") is False


async def test_add_label(http: FakeHttp, client: GitHubClient) -> None:
    http.on("POST", f"{BASE}/issues/7/labels", body=[])
    await client.add_label(REPO, 7, "major-ready")
    assert _api_requests(http)[0].json() == {"labels": ["major-ready"]}


async def test_remove_label_quotes_the_name(http: FakeHttp, client: GitHubClient) -> None:
    http.on("DELETE", f"{BASE}/issues/7/labels/update%20broken", body=[])
    await client.remove_label(REPO, 7, "update broken")
    assert _api_requests(http)[0].path.endswith("/labels/update%20broken")


async def test_remove_label_ignores_404(http: FakeHttp, client: GitHubClient) -> None:
    http.on(
        "DELETE", f"{BASE}/issues/7/labels/major-ready", 404, {"message": "Label does not exist"}
    )
    await client.remove_label(REPO, 7, "major-ready")


async def test_comment(http: FakeHttp, client: GitHubClient) -> None:
    http.on("POST", f"{BASE}/issues/7/comments", 201, {"id": 1})
    await client.comment(REPO, 7, "@dependabot rebase")
    assert _api_requests(http)[0].json() == {"body": "@dependabot rebase"}


async def test_unexpected_status_raises_github_error_without_token_in_message(
    http: FakeHttp, client: GitHubClient
) -> None:
    http.on("GET", f"{BASE}/compare/main...abc", 500, {"message": "boom"})
    with pytest.raises(GitHubError) as raised:
        await client.behind_by(REPO, "main", "abc")
    assert raised.value.status == 500
    assert raised.value.path == f"{BASE}/compare/main...abc"
    assert "ghs_x" not in str(raised.value)


async def test_failed_token_exchange_raises_github_error(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on("POST", "/app/installations/42/access_tokens", 401, {"message": "Bad credentials"})
    client = GitHubClient(
        http, InstallationTokens(http, "123", CryptographySigner(rsa_key), lambda: 0.0), 42
    )
    with pytest.raises(GitHubError) as raised:
        await client.behind_by(REPO, "main", "abc")
    assert raised.value.status == 401
