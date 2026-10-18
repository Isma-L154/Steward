import base64
import json
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from steward.github.http import GitHubError, HttpClient

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

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


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def app_jwt(app_id: str, key: RSAPrivateKey, now: int) -> str:
    # Imported here: cryptography reads entropy on import, forbidden at Worker startup.
    from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15  # noqa: PLC0415
    from cryptography.hazmat.primitives.hashes import SHA256  # noqa: PLC0415

    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = {"iat": now - _CLOCK_SKEW_SECONDS, "exp": now + _JWT_LIFETIME_SECONDS, "iss": app_id}
    payload = _b64url(json.dumps(claims).encode())
    signing_input = f"{header}.{payload}".encode()
    return f"{header}.{payload}.{_b64url(key.sign(signing_input, PKCS1v15(), SHA256()))}"


class InstallationTokens:
    def __init__(
        self, http: HttpClient, app_id: str, key: RSAPrivateKey, clock: Callable[[], float]
    ) -> None:
        self._http = http
        self._app_id = app_id
        self._key = key
        self._clock = clock
        self._cache: dict[int, tuple[str, float]] = {}

    async def token(self, installation_id: int) -> str:
        cached = self._cache.get(installation_id)
        if cached is not None and self._clock() < cached[1] - _REFRESH_MARGIN_SECONDS:
            return cached[0]
        path = f"/app/installations/{installation_id}/access_tokens"
        jwt = app_jwt(self._app_id, self._key, int(self._clock()))
        headers = {**API_HEADERS, "Authorization": f"Bearer {jwt}"}
        response = await self._http.request("POST", f"{API}{path}", headers)
        if response.status != 201:  # noqa: PLR2004 - GitHub's "Created"
            raise GitHubError(response.status, path)
        body = json.loads(response.body)
        expires_at = datetime.fromisoformat(body["expires_at"]).timestamp()
        self._cache[installation_id] = (body["token"], expires_at)
        return str(body["token"])
