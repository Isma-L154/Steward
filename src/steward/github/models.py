from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class CheckState(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"


@dataclass(frozen=True)
class CheckResult:
    name: str
    state: CheckState
