from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str


class HttpClient(Protocol):
    async def request(
        self, method: str, url: str, headers: Mapping[str, str], body: str | None = None
    ) -> HttpResponse: ...


class GitHubError(Exception):
    """An unexpected GitHub answer. Carries the status and path only, never a token."""

    def __init__(self, status: int, path: str) -> None:
        super().__init__(f"GitHub answered {status} for {path}")
        self.status = status
        self.path = path
