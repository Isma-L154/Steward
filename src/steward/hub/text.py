import re
import unicodedata
from datetime import UTC, datetime

from steward.github.models import RepoRef

MAX_TITLE = 200
URL_PATTERN = re.compile(
    r"^https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+(/(pull|issues)/[0-9]+)?$"
)
_OWNER = re.compile(r"[A-Za-z0-9-]+")
_NAME = re.compile(r"[A-Za-z0-9._-]+")
_UNCHECKED = re.compile(r"^- \[ \] ", re.MULTILINE)
# Cf covers the bidi overrides that make text render differently from what it says.
_INVISIBLE = {"Cc", "Cf"}


def is_safe_repo(repo: RepoRef) -> bool:
    return (
        _OWNER.fullmatch(repo.owner) is not None
        and _NAME.fullmatch(repo.name) is not None
        and repo.name not in {".", ".."}
    )


def repo_url(repo: RepoRef) -> str:
    if not is_safe_repo(repo):
        raise ValueError("unsafe repository name")
    return f"https://github.com/{repo.owner}/{repo.name}"


def _item_url(repo: RepoRef, kind: str, number: int) -> str:
    if number < 1:
        raise ValueError("invalid number")
    return f"{repo_url(repo)}/{kind}/{number}"


def pull_url(repo: RepoRef, number: int) -> str:
    return _item_url(repo, "pull", number)


def issue_url(repo: RepoRef, number: int) -> str:
    return _item_url(repo, "issues", number)


def clean_title(raw: str) -> str:
    visible = "".join(
        " " if char.isspace() else char
        for char in raw
        if char.isspace() or unicodedata.category(char) not in _INVISIBLE
    )
    return " ".join(visible.split())[:MAX_TITLE]


def unchecked_findings(body: str) -> int:
    return len(_UNCHECKED.findall(body))


def iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
