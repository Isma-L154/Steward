from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from steward.github.models import RepoRef

MAX_BODY_BYTES = 1_048_576
_DEPENDABOT_BRANCH_PREFIX = "dependabot/"


class InvalidPayload(Exception):
    """The webhook body is not the shape this App relies on."""


@dataclass(frozen=True)
class PullRequestToEvaluate:
    installation_id: int
    repo: RepoRef
    number: int


# GitHub payloads carry hundreds of fields: only the ones used are declared, strictly typed.
class _Model(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)


class _Head(_Model):
    ref: str


class _PullRequest(_Model):
    number: int
    head: _Head


class _WorkflowRun(_Model):
    pull_requests: list[_PullRequest]


class _Owner(_Model):
    login: str


class _Repository(_Model):
    name: str
    owner: _Owner


class _Installation(_Model):
    id: int


class _WorkflowRunEvent(_Model):
    action: str
    installation: _Installation
    repository: _Repository
    workflow_run: _WorkflowRun


class _Action(_Model):
    action: str


def pull_requests_to_evaluate(event: str, body: str) -> list[PullRequestToEvaluate]:
    """The Dependabot pull requests whose CI just finished, or none for any other event."""
    if event != "workflow_run":
        return []
    try:
        if _Action.model_validate_json(body).action != "completed":
            return []
        parsed = _WorkflowRunEvent.model_validate_json(body)
    except ValidationError as error:
        raise InvalidPayload(str(error.error_count())) from error
    repo = RepoRef(parsed.repository.owner.login, parsed.repository.name)
    return [
        PullRequestToEvaluate(parsed.installation.id, repo, pr.number)
        for pr in parsed.workflow_run.pull_requests
        if pr.head.ref.startswith(_DEPENDABOT_BRANCH_PREFIX)
    ]
