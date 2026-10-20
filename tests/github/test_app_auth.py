import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.hashes import SHA256

from steward.github.app_auth import (
    InstallationTokens,
    app_jwt,
    bot_login,
    installations,
    uninstall,
)
from steward.github.http import GitHubError
from steward.github.models import Installation
from tests.github.fake_http import FakeHttp
from tests.github.signer import CryptographySigner

ROUTE = "/app/installations/42/access_tokens"


def _b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


async def test_app_jwt_is_rs256_with_backdated_iat_and_ten_minute_cap(
    rsa_key: RSAPrivateKey,
) -> None:
    token = await app_jwt("123", CryptographySigner(rsa_key), now=1_000_000)
    header, payload, signature = token.split(".")
    assert json.loads(_b64url_decode(header)) == {"alg": "RS256", "typ": "JWT"}
    assert json.loads(_b64url_decode(payload)) == {"iat": 999_940, "exp": 1_000_540, "iss": "123"}
    rsa_key.public_key().verify(
        _b64url_decode(signature), f"{header}.{payload}".encode(), PKCS1v15(), SHA256()
    )
    assert "=" not in token


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _tokens(http: FakeHttp, clock: _Clock, rsa_key: RSAPrivateKey) -> InstallationTokens:
    return InstallationTokens(http, "123", CryptographySigner(rsa_key), clock)


async def test_installation_token_uses_the_app_jwt(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on("POST", ROUTE, 201, {"token": "ghs_one", "expires_at": "2026-10-18T13:00:00Z"})
    clock = _Clock(1_792_324_800.0)  # 2026-10-18T12:00:00Z
    assert await _tokens(http, clock, rsa_key).token(42) == "ghs_one"
    authorization = http.requests[0].headers["Authorization"]
    assert authorization.startswith("Bearer ")
    assert authorization.removeprefix("Bearer ").count(".") == 2


async def test_installation_token_is_cached_until_five_minutes_before_expiry(
    rsa_key: RSAPrivateKey,
) -> None:
    http = FakeHttp()
    http.on("POST", ROUTE, 201, {"token": "ghs_one", "expires_at": "2026-10-18T13:00:00Z"})
    clock = _Clock(1_792_324_800.0)
    tokens = _tokens(http, clock, rsa_key)
    await tokens.token(42)
    clock.now += 3600 - 301
    assert await tokens.token(42) == "ghs_one"
    assert len(http.requests) == 1


async def test_installation_token_refreshed_after_that(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on("POST", ROUTE, 201, {"token": "ghs_one", "expires_at": "2026-10-18T13:00:00Z"})
    clock = _Clock(1_792_324_800.0)
    tokens = _tokens(http, clock, rsa_key)
    await tokens.token(42)
    http.on("POST", ROUTE, 201, {"token": "ghs_two", "expires_at": "2026-10-18T14:00:00Z"})
    clock.now += 3600 - 299
    assert await tokens.token(42) == "ghs_two"
    assert len(http.requests) == 2


async def test_bot_login_is_the_app_slug_with_bot_suffix(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on("GET", "/app", body={"id": 5373045, "slug": "app-steward"})
    login = await bot_login(http, "123", CryptographySigner(rsa_key), now=1_000_000)
    assert login == "app-steward[bot]"
    assert http.requests[0].headers["Authorization"].startswith("Bearer ")


async def test_installations_lists_each_with_its_account(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on(
        "GET",
        "/app/installations",
        body=[{"id": 42, "account": {"login": "Isma-L154"}}, {"id": 7, "account": None}],
    )
    assert await installations(http, "123", CryptographySigner(rsa_key), now=1_000_000) == [
        Installation(42, "Isma-L154"),
        Installation(7, ""),
    ]
    assert http.requests[0].headers["Authorization"].startswith("Bearer ")


async def test_uninstall_deletes_another_accounts_installation(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on("GET", "/app", body={"slug": "app-steward", "owner": {"login": "Isma-L154"}})
    http.on("DELETE", "/app/installations/7", 204)
    removed = await uninstall(
        http, "123", CryptographySigner(rsa_key), 1_000_000, Installation(7, "x")
    )
    assert removed
    assert [(r.method, r.path) for r in http.requests] == [
        ("GET", "/app"),
        ("DELETE", "/app/installations/7"),
    ]


@pytest.mark.parametrize("account", ["Isma-L154", "isma-l154"])
async def test_uninstall_never_removes_the_apps_own_account(
    rsa_key: RSAPrivateKey, account: str
) -> None:
    http = FakeHttp()
    http.on("GET", "/app", body={"slug": "app-steward", "owner": {"login": "Isma-L154"}})
    removed = await uninstall(
        http, "123", CryptographySigner(rsa_key), 1_000_000, Installation(42, account)
    )
    assert not removed
    assert all(request.method != "DELETE" for request in http.requests)


async def test_refused_uninstall_raises(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on("GET", "/app", body={"slug": "app-steward", "owner": {"login": "Isma-L154"}})
    http.on("DELETE", "/app/installations/7", 404, {"message": "Not Found"})
    with pytest.raises(GitHubError) as raised:
        await uninstall(http, "123", CryptographySigner(rsa_key), 1_000_000, Installation(7, "x"))
    assert raised.value.status == 404


async def test_scoped_token_request_carries_exactly_the_permissions(
    rsa_key: RSAPrivateKey,
) -> None:
    http = FakeHttp()
    http.on(
        "POST",
        ROUTE,
        201,
        {
            "token": "ghs_ro",
            "expires_at": "2026-10-18T13:00:00Z",
            "permissions": {"metadata": "read"},
        },
    )
    clock = _Clock(1_792_324_800.0)
    tokens = InstallationTokens(
        http, "123", CryptographySigner(rsa_key), clock, permissions={"metadata": "read"}
    )
    assert await tokens.token(42) == "ghs_ro"
    assert http.requests[0].json() == {"permissions": {"metadata": "read"}}


async def test_unscoped_token_request_has_no_body(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on("POST", ROUTE, 201, {"token": "ghs_one", "expires_at": "2026-10-18T13:00:00Z"})
    await _tokens(http, _Clock(1_792_324_800.0), rsa_key).token(42)
    assert http.requests[0].body is None


async def test_scoped_token_wider_than_asked_is_refused(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on(
        "POST",
        ROUTE,
        201,
        {
            "token": "ghs_full",
            "expires_at": "2026-10-18T13:00:00Z",
            "permissions": {"metadata": "read", "contents": "write"},
        },
    )
    tokens = InstallationTokens(
        http, "123", CryptographySigner(rsa_key), _Clock(1_792_324_800.0), {"metadata": "read"}
    )
    with pytest.raises(GitHubError):
        await tokens.token(42)


async def test_scoped_token_without_permissions_in_answer_is_refused(
    rsa_key: RSAPrivateKey,
) -> None:
    http = FakeHttp()
    http.on("POST", ROUTE, 201, {"token": "ghs_x", "expires_at": "2026-10-18T13:00:00Z"})
    tokens = InstallationTokens(
        http, "123", CryptographySigner(rsa_key), _Clock(1_792_324_800.0), {"metadata": "read"}
    )
    with pytest.raises(GitHubError):
        await tokens.token(42)


async def test_refused_token_request_carries_github_message(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on(
        "POST",
        ROUTE,
        422,
        {
            "message": "There is at least one permission requested that is not granted.",
            "documentation_url": "https://docs.github.com/rest/apps/apps",
        },
    )
    tokens = InstallationTokens(
        http, "123", CryptographySigner(rsa_key), _Clock(1_792_324_800.0), {"metadata": "read"}
    )
    with pytest.raises(GitHubError) as raised:
        await tokens.token(42)
    assert raised.value.detail == (
        "There is at least one permission requested that is not granted. "
        "(https://docs.github.com/rest/apps/apps)"
    )
    jwt = http.requests[-1].headers["Authorization"].removeprefix("Bearer ")
    assert jwt not in str(raised.value)


async def test_wider_token_is_refused_with_a_reason(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on(
        "POST",
        ROUTE,
        201,
        {
            "token": "ghs_full",
            "expires_at": "2026-10-18T13:00:00Z",
            "permissions": {"metadata": "read", "contents": "write"},
        },
    )
    tokens = InstallationTokens(
        http, "123", CryptographySigner(rsa_key), _Clock(1_792_324_800.0), {"metadata": "read"}
    )
    with pytest.raises(GitHubError) as raised:
        await tokens.token(42)
    assert raised.value.detail == "granted permissions differ from the request"
    assert "ghs_full" not in str(raised.value)


async def test_refused_app_lookup_carries_github_message(rsa_key: RSAPrivateKey) -> None:
    http = FakeHttp()
    http.on("GET", "/app", 401, {"message": "Bad credentials"})
    with pytest.raises(GitHubError) as raised:
        await bot_login(http, "123", CryptographySigner(rsa_key), 1_792_324_800)
    assert raised.value.detail == "Bad credentials"
