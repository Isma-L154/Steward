import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from steward.github.api import GitHubApi
from steward.github.app_auth import InstallationTokens
from steward.github.http import GitHubError
from tests.github.fake_http import FakeHttp
from tests.github.signer import CryptographySigner


def _api(http: FakeHttp, rsa_key: RSAPrivateKey) -> GitHubApi:
    http.on(
        "POST",
        "/app/installations/42/access_tokens",
        201,
        {"token": "ghs_x", "expires_at": "2099-01-01T00:00:00Z"},
    )
    tokens = InstallationTokens(http, "123", CryptographySigner(rsa_key), lambda: 0.0)
    return GitHubApi(http, tokens, 42)


async def test_call_returns_status_and_json(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    api = _api(http, rsa_key)
    http.on("GET", "/repos/a/b", body={"name": "b"})
    assert await api.call("GET", "/repos/a/b") == (200, {"name": "b"})


async def test_graphql_returns_data_and_sends_variables(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    api = _api(http, rsa_key)
    http.on("POST", "/graphql", body={"data": {"viewer": {"login": "x"}}})
    assert await api.graphql("query { viewer { login } }", {"a": 1}) == {"viewer": {"login": "x"}}
    sent = http.requests[-1].json()
    assert sent == {"query": "query { viewer { login } }", "variables": {"a": 1}}
    assert http.requests[-1].headers["Authorization"] == "Bearer ghs_x"


async def test_graphql_errors_raise(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    api = _api(http, rsa_key)
    http.on("POST", "/graphql", body={"data": None, "errors": [{"message": "boom"}]})
    with pytest.raises(GitHubError) as raised:
        await api.graphql("query { x }", {})
    assert raised.value.path == "/graphql"


async def test_graphql_partial_returns_data_despite_errors(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    api = _api(http, rsa_key)
    http.on("POST", "/graphql", body={"data": {"r0": None}, "errors": [{"path": ["r0"]}]})
    assert await api.graphql_partial("query { x }", {}) == {"r0": None}


async def test_graphql_partial_without_data_raises(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    api = _api(http, rsa_key)
    http.on("POST", "/graphql", body={"errors": [{"message": "boom"}]})
    with pytest.raises(GitHubError) as raised:
        await api.graphql_partial("query { x }", {})
    assert raised.value.status == 200
    assert raised.value.path == "/graphql"
