import re
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from steward.github.api import GitHubApi
from steward.github.hub_client import (
    READ_ONLY_PERMISSIONS,
    HubClient,
    account_repos,
    build_query,
    parse_repo,
    read_only_tokens,
)
from steward.github.models import RepoRef
from steward.hub.snapshot import HubRepo, OpenIssue, OpenPull
from tests.github.fake_http import FakeHttp
from tests.github.signer import CryptographySigner

ACCESS_TOKENS_PATH = "/app/installations/42/access_tokens"
REPO = RepoRef("o", "a")


def _block(**overrides: Any) -> dict[str, Any]:
    block: dict[str, Any] = {
        "defaultBranchRef": {
            "target": {
                "committedDate": "2026-10-18T20:59:02Z",
                "statusCheckRollup": {"state": "SUCCESS"},
            }
        },
        "deployments": {
            "nodes": [{"createdAt": "2026-10-18T21:04:11Z", "latestStatus": {"state": "SUCCESS"}}]
        },
        "pullRequests": {
            "totalCount": 1,
            "nodes": [
                {
                    "number": 12,
                    "title": "Bump x",
                    "author": {"login": "dependabot"},
                    "labels": {"nodes": [{"name": "major-ready"}]},
                }
            ],
        },
        "issues": {"totalCount": 2},
        "standards": {
            "totalCount": 1,
            "nodes": [{"number": 7, "author": {"login": "app-steward"}, "body": "- [ ] a"}],
        },
        "vulnerabilityAlerts": {
            "totalCount": 1,
            "nodes": [{"securityVulnerability": {"severity": "HIGH"}}],
        },
    }
    block.update(overrides)
    return block


def _installed(*names: str, archived: bool = False, topics: tuple[str, ...] = ()) -> dict[str, Any]:
    repositories = [
        {"name": name, "owner": {"login": "o"}, "archived": archived, "topics": list(topics)}
        for name in names
    ]
    return {"total_count": len(repositories), "repositories": repositories}


def _client(http: FakeHttp, rsa_key: RSAPrivateKey, label: str = "standards") -> HubClient:
    http.on(
        "POST",
        ACCESS_TOKENS_PATH,
        201,
        {
            "token": "ghs_ro",
            "expires_at": "2099-01-01T00:00:00Z",
            "permissions": dict(READ_ONLY_PERMISSIONS),
        },
    )
    tokens = read_only_tokens(http, "123", CryptographySigner(rsa_key), lambda: 0.0)
    return HubClient(GitHubApi(http, tokens, 42), label)


def test_query_aliases_and_variables() -> None:
    query = build_query(2)
    assert "$o0: String!" in query
    assert "$n0: String!" in query
    assert "$o1: String!" in query
    assert "$n1: String!" in query
    assert "r0: repository(owner: $o0, name: $n0)" in query
    assert "r1: repository(owner: $o1, name: $n1)" in query
    assert 'environments: ["production"]' in query
    assert "$label: String!" in query
    assert "labels: [$label]" in query
    assert re.search(r"pullRequests\([^)]*\)\s*\{\s*totalCount", query)
    assert re.search(r"vulnerabilityAlerts\([^)]*\)\s*\{\s*totalCount", query)
    assert "r2:" not in query


def test_parse_full_block() -> None:
    assert parse_repo(REPO, _block()) == HubRepo(
        REPO,
        ci_state="SUCCESS",
        last_commit_at=datetime(2026, 10, 18, 20, 59, 2, tzinfo=UTC),
        deploy_state="SUCCESS",
        deploy_at=datetime(2026, 10, 18, 21, 4, 11, tzinfo=UTC),
        pulls_open=1,
        pulls=(OpenPull(12, "Bump x", "dependabot", frozenset({"major-ready"})),),
        issues_open=2,
        standards_issues=(OpenIssue(7, "app-steward", "- [ ] a"),),
        alert_severities=("HIGH",),
    )


async def test_refresh_makes_three_calls_per_installation(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    client = _client(http, rsa_key)
    names = [f"r{index}" for index in range(30)]
    http.on("GET", "/installation/repositories", body=_installed(*names))
    http.on("POST", "/graphql", body={"data": {f"r{i}": _block() for i in range(30)}})
    repos = await client.repos()
    assert len(repos) == 30
    assert [(request.method, request.path) for request in http.requests] == [
        ("POST", ACCESS_TOKENS_PATH),
        ("GET", "/installation/repositories"),
        ("POST", "/graphql"),
    ]
    assert http.requests[0].json() == {"permissions": dict(READ_ONLY_PERMISSIONS)}
    variables = http.requests[2].json()["variables"]
    assert variables["label"] == "standards"
    assert variables["o0"] == "o"
    assert variables["n29"] == "r29"


def test_read_only_permissions_are_exactly_reads() -> None:
    assert set(READ_ONLY_PERMISSIONS.values()) == {"read"}
    assert dict(READ_ONLY_PERMISSIONS) == {
        "metadata": "read",
        # Private repositories return their default branch and commits only with this.
        "contents": "read",
        "pull_requests": "read",
        "issues": "read",
        "checks": "read",
        "statuses": "read",
        "deployments": "read",
        "vulnerability_alerts": "read",
    }


async def test_no_managed_repos_sends_no_graphql(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    client = _client(http, rsa_key)
    archived = _installed("old", archived=True)
    ignored = _installed("skip", topics=("steward-ignore",))
    http.on(
        "GET",
        "/installation/repositories",
        body={"repositories": archived["repositories"] + ignored["repositories"]},
    )
    assert await client.repos() == []
    assert all(request.path != "/graphql" for request in http.requests)


async def test_unsafe_repo_names_are_dropped_before_the_query(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    client = _client(http, rsa_key)
    http.on("GET", "/installation/repositories", body=_installed("good", ".."))
    http.on("POST", "/graphql", body={"data": {"r0": _block()}})
    repos = await client.repos()
    assert [repo.repo for repo in repos] == [RepoRef("o", "good")]
    assert http.requests[-1].json()["variables"] == {"label": "standards", "o0": "o", "n0": "good"}


async def test_null_repository_reads_unknown_others_unaffected(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    client = _client(http, rsa_key)
    http.on("GET", "/installation/repositories", body=_installed("gone", "here"))
    http.on(
        "POST",
        "/graphql",
        body={"data": {"r0": None, "r1": _block()}, "errors": [{"path": ["r0"]}]},
    )
    gone, here = await client.repos()
    assert gone == HubRepo(RepoRef("o", "gone"))
    assert here.ci_state == "SUCCESS"


def test_null_field_reads_unknown_for_that_field_only() -> None:
    repo = parse_repo(REPO, _block(vulnerabilityAlerts=None))
    assert repo.alert_severities is None
    assert repo.ci_state == "SUCCESS"
    assert repo.pulls_open == 1


def test_truncated_connections_read_none() -> None:
    pulls = _block()["pullRequests"]
    alerts = _block()["vulnerabilityAlerts"]
    standards = _block()["standards"]
    repo = parse_repo(
        REPO,
        _block(
            pullRequests={**pulls, "totalCount": 150},
            vulnerabilityAlerts={**alerts, "totalCount": 101},
            standards={**standards, "totalCount": 6},
        ),
    )
    assert repo.pulls is None
    assert repo.pulls_open == 150
    assert repo.alert_severities is None
    assert repo.standards_issues is None


def test_wrong_type_in_one_repo_makes_that_repo_unknown() -> None:
    assert parse_repo(REPO, _block(issues={"totalCount": "3"})) == HubRepo(REPO)


def test_bad_timestamp_makes_that_repo_unknown() -> None:
    ref = {"target": {"committedDate": "yesterday", "statusCheckRollup": None}}
    assert parse_repo(REPO, _block(defaultBranchRef=ref)) == HubRepo(REPO)


def test_empty_repo_without_default_branch() -> None:
    repo = parse_repo(REPO, _block(defaultBranchRef=None))
    assert repo.ci_state is None
    assert repo.last_commit_at is None
    assert repo.issues_open == 2


def test_no_deployment_and_alert_without_vulnerability() -> None:
    repo = parse_repo(
        REPO,
        _block(
            deployments={"nodes": []},
            vulnerabilityAlerts={"totalCount": 1, "nodes": [{"securityVulnerability": None}]},
        ),
    )
    assert repo.deploy_state is None
    assert repo.deploy_at is None
    assert repo.alert_severities == ("UNKNOWN",)


async def test_account_repos_concatenates_installations() -> None:
    class _Client:
        def __init__(self, installation: int) -> None:
            self.installation = installation

        async def repos(self) -> list[HubRepo]:
            return [HubRepo(RepoRef("o", f"i{self.installation}"))]

    repos = await account_repos([1, 2], _Client)  # type: ignore[arg-type]
    assert [repo.repo.name for repo in repos] == ["i1", "i2"]


async def test_standards_issues_are_read_by_the_given_label(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    client = _client(http, rsa_key, "quality")
    http.on("GET", "/installation/repositories", body=_installed("a"))
    http.on("POST", "/graphql", body={"data": {"r0": _block()}})
    await client.repos()
    assert http.requests[-1].json()["variables"]["label"] == "quality"
