from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

DEPENDABOT_LOGIN = "dependabot[bot]"


def graphql_login(rest_login: str) -> str:
    """GraphQL names every bot by its bare login, without the `[bot]` suffix REST uses."""
    return rest_login.removesuffix("[bot]")


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class InstalledRepo:
    repo: RepoRef
    archived: bool
    topics: tuple[str, ...]


@dataclass(frozen=True)
class TrackingIssue:
    number: int
    state: str
    body: str


class BranchUpdate(StrEnum):
    UPDATED = "updated"
    NOT_NOW = "not_now"  # the head moved, or main does not merge in cleanly
    FORBIDDEN = "forbidden"  # e.g. the App may not write workflow files


class CheckState(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"


@dataclass(frozen=True)
class CheckResult:
    name: str
    state: CheckState


@dataclass(frozen=True)
class PullRequest:
    number: int
    state: str
    draft: bool
    author: str
    head_sha: str
    base_ref: str
    mergeable: bool | None
    labels: frozenset[str]


@dataclass(frozen=True)
class Commit:
    author: str | None
    message: str


type MergeMethod = Literal["squash", "merge", "rebase"]
