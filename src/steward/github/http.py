import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

MAX_DETAIL = 200
# GitHub's messages do not echo credentials; this keeps any that did out of the logs anyway.
_SECRET = re.compile(r"(?:gh[opsur]_|github_pat_)\w+|eyJ[\w-]*\.[\w-]*\.[\w-]*|(?i:bearer)\s+\S+")
_DOCS = "https://docs.github.com/"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str


class HttpClient(Protocol):
    async def request(
        self, method: str, url: str, headers: Mapping[str, str], body: str | None = None
    ) -> HttpResponse: ...


def _message(answer: object) -> tuple[object, object]:
    if not isinstance(answer, dict):
        return None, None
    errors = answer.get("errors")
    if "message" not in answer and isinstance(errors, list) and errors:
        first = errors[0]
        return (first.get("message") if isinstance(first, dict) else None), None
    return answer.get("message"), answer.get("documentation_url")


def _clean(text: str) -> str:
    visible = "".join(" " if unicodedata.category(char)[0] == "C" else char for char in text)
    return " ".join(_SECRET.sub("[redacted]", visible).split())[:MAX_DETAIL]


def detail_from(answer: object) -> str | None:
    """GitHub's own explanation of a refusal, made safe for a log line: bounded, on one line,
    and with anything shaped like a credential redacted."""
    message, docs = _message(answer)
    if not isinstance(message, str):
        return None
    if isinstance(docs, str) and docs.startswith(_DOCS):
        message = f"{message} ({docs})"
    return _clean(message) or None


def answer_detail(body: str) -> str | None:
    try:
        return detail_from(json.loads(body))
    except ValueError:
        return None


class GitHubError(Exception):
    """An unexpected GitHub answer. Carries the status, the path and GitHub's sanitized
    message, never a token or a request body."""

    def __init__(self, status: int, path: str, detail: str | None = None) -> None:
        suffix = f": {detail}" if detail else ""
        super().__init__(f"GitHub answered {status} for {path}{suffix}")
        self.status = status
        self.path = path
        self.detail = detail
