import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from steward.github.http import HttpResponse


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: str
    headers: Mapping[str, str]
    body: str | None

    def json(self) -> Any:
        return json.loads(self.body or "null")


@dataclass
class FakeHttp:
    """Answers by (method, path without query); unknown routes are a test failure (599)."""

    routes: dict[tuple[str, str], HttpResponse] = field(default_factory=dict)
    requests: list[Request] = field(default_factory=list)

    def on(self, method: str, path: str, status: int = 200, body: Any = None) -> None:
        self.routes[(method, path)] = HttpResponse(status, "" if body is None else json.dumps(body))

    async def request(
        self, method: str, url: str, headers: Mapping[str, str], body: str | None = None
    ) -> HttpResponse:
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "api.github.com"
        self.requests.append(Request(method, parsed.path, parsed.query, dict(headers), body))
        return self.routes.get((method, parsed.path), HttpResponse(599, "no route"))
