import base64
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from steward.github.http import GitHubError, HttpClient, answer_detail
from steward.github.models import Installation

API = "https://api.github.com"
API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "steward",
}
# GitHub rejects an App JWT issued in the future or valid for more than ten minutes.
_CLOCK_SKEW_SECONDS = 60
_JWT_LIFETIME_SECONDS = 540
_REFRESH_MARGIN_SECONDS = 300


class Signer(Protocol):
    """RS256: an RSASSA-PKCS1-v1_5 signature over SHA-256 with the App's private key."""

    async def sign(self, data: bytes) -> bytes: ...


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


async def app_jwt(app_id: str, signer: Signer, now: int) -> str:
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = {"iat": now - _CLOCK_SKEW_SECONDS, "exp": now + _JWT_LIFETIME_SECONDS, "iss": app_id}
    payload = _b64url(json.dumps(claims).encode())
    signing_input = f"{header}.{payload}".encode()
    return f"{header}.{payload}.{_b64url(await signer.sign(signing_input))}"


async def _app_call(http: HttpClient, jwt: str, method: str, path: str, ok: int) -> Any:
    headers = {**API_HEADERS, "Authorization": f"Bearer {jwt}"}
    response = await http.request(method, f"{API}{path}", headers)
    if response.status != ok:
        route = path.split("?", maxsplit=1)[0]
        raise GitHubError(response.status, route, answer_detail(response.body))
    return json.loads(response.body) if response.body else None


async def bot_login(http: HttpClient, app_id: str, signer: Signer, now: int) -> str:
    """The login this App's commits and comments carry, e.g. `app-steward[bot]`."""
    app = await _app_call(http, await app_jwt(app_id, signer, now), "GET", "/app", 200)
    return f"{app['slug']}[bot]"


async def installations(
    http: HttpClient, app_id: str, signer: Signer, now: int
) -> list[Installation]:
    jwt = await app_jwt(app_id, signer, now)
    items = await _app_call(http, jwt, "GET", "/app/installations?per_page=100", 200)
    return [
        Installation(int(item["id"]), (item.get("account") or {}).get("login", ""))
        for item in items
    ]


async def uninstall(
    http: HttpClient, app_id: str, signer: Signer, now: int, installation: Installation
) -> bool:
    """Removes the App from another account. The App's own account is never removed, whatever
    the configuration says: a mistyped owner must not uninstall the owner."""
    jwt = await app_jwt(app_id, signer, now)
    app = await _app_call(http, jwt, "GET", "/app", 200)
    if installation.account.lower() == str(app["owner"]["login"]).lower():
        print(f"installation {installation.id}: refusing to uninstall the App's own account")
        return False
    await _app_call(http, jwt, "DELETE", f"/app/installations/{installation.id}", 204)
    return True


def _within(granted: object, asked: Mapping[str, str]) -> bool:
    return isinstance(granted, dict) and all(
        asked.get(key) == level for key, level in granted.items()
    )


class InstallationTokens:
    def __init__(
        self,
        http: HttpClient,
        app_id: str,
        signer: Signer,
        clock: Callable[[], float],
        permissions: Mapping[str, str] | None = None,
    ) -> None:
        self._http = http
        # A token narrowed to these permissions; each instance caches its own tokens, so a
        # narrowed instance never hands out the App's full token.
        self._permissions = None if permissions is None else dict(permissions)
        self._body = None if permissions is None else json.dumps({"permissions": dict(permissions)})
        self._app_id = app_id
        self._signer = signer
        self._clock = clock
        self._cache: dict[int, tuple[str, float]] = {}

    async def token(self, installation_id: int) -> str:
        cached = self._cache.get(installation_id)
        if cached is not None and self._clock() < cached[1] - _REFRESH_MARGIN_SECONDS:
            return cached[0]
        path = f"/app/installations/{installation_id}/access_tokens"
        jwt = await app_jwt(self._app_id, self._signer, int(self._clock()))
        headers = {**API_HEADERS, "Authorization": f"Bearer {jwt}"}
        response = await self._http.request("POST", f"{API}{path}", headers, self._body)
        if response.status != 201:  # noqa: PLR2004 - GitHub's "Created"
            raise GitHubError(response.status, path, answer_detail(response.body))
        body = json.loads(response.body)
        # GitHub states the token's permissions; one wider than asked must never be used.
        if self._permissions is not None and not _within(
            body.get("permissions"), self._permissions
        ):
            raise GitHubError(response.status, path, "granted permissions differ from the request")
        expires_at = datetime.fromisoformat(body["expires_at"]).timestamp()
        self._cache[installation_id] = (body["token"], expires_at)
        return str(body["token"])
