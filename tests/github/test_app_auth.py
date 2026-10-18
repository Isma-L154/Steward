import base64
import json

from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.hashes import SHA256

from steward.github.app_auth import InstallationTokens, app_jwt
from tests.github.fake_http import FakeHttp

ROUTE = "/app/installations/42/access_tokens"


def _b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_app_jwt_is_rs256_with_backdated_iat_and_ten_minute_cap(rsa_key: RSAPrivateKey) -> None:
    token = app_jwt("123", rsa_key, now=1_000_000)
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
    return InstallationTokens(http, "123", rsa_key, clock)


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
