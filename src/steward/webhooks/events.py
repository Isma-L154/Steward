from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from steward.accounts import Accounts
from steward.github.models import Installation, RepoRef
from steward.repos import is_managed

MAX_BODY_BYTES = 1_048_576
_DEPENDABOT_BRANCH_PREFIX = "dependabot/"


class InvalidPayload(Exception):
    """The webhook body is not the shape this App relies on."""


@dataclass(frozen=True)
class PullRequestToEvaluate:
    installation_id: int
    repo: RepoRef
    number: int


@dataclass(frozen=True)
class PushToDefault:
    installation_id: int
    repo: RepoRef
    # Standards are the owner's rules: other allowed accounts get merges only.
    audit: bool


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
    archived: bool = False
    topics: list[str] = []


class _PushedRepository(_Repository):
    default_branch: str


class _Installation(_Model):
    id: int


class _InstalledAccount(_Installation):
    account: _Owner | None


class _InstallationEvent(_Model):
    action: str
    installation: _InstalledAccount


class _WorkflowRunEvent(_Model):
    action: str
    installation: _Installation
    repository: _Repository
    workflow_run: _WorkflowRun


class _Action(_Model):
    action: str


class _PushEvent(_Model):
    ref: str
    installation: _Installation
    repository: _PushedRepository


# Actions that grant the App access to an account's repositories.
_GRANTS = {"installation": "created", "installation_repositories": "added"}


def pull_requests_to_evaluate(
    event: str, body: str, accounts: Accounts
) -> list[PullRequestToEvaluate]:
    """The Dependabot pull requests whose CI just finished, or none for any other event."""
    if event != "workflow_run":
        return []
    try:
        if _Action.model_validate_json(body).action != "completed":
            return []
        parsed = _WorkflowRunEvent.model_validate_json(body)
    except ValidationError as error:
        raise InvalidPayload(str(error.error_count())) from error
    if not is_managed(parsed.repository.archived, parsed.repository.topics):
        return []
    if not accounts.may_act(parsed.repository.owner.login):
        return []
    repo = RepoRef(parsed.repository.owner.login, parsed.repository.name)
    return [
        PullRequestToEvaluate(parsed.installation.id, repo, pr.number)
        for pr in parsed.workflow_run.pull_requests
        if pr.head.ref.startswith(_DEPENDABOT_BRANCH_PREFIX)
    ]


def pushes_to_default(event: str, body: str, accounts: Accounts) -> list[PushToDefault]:
    """The repository whose default branch just moved, or none for any other event."""
    if event != "push":
        return []
    try:
        parsed = _PushEvent.model_validate_json(body)
    except ValidationError as error:
        raise InvalidPayload(str(error.error_count())) from error
    repository = parsed.repository
    if parsed.ref != f"refs/heads/{repository.default_branch}" or not is_managed(
        repository.archived, repository.topics
    ):
        return []
    if not accounts.may_act(repository.owner.login):
        return []
    owner = repository.owner.login
    return [
        PushToDefault(
            parsed.installation.id, RepoRef(owner, repository.name), accounts.is_owner(owner)
        )
    ]


def installation_to_remove(event: str, body: str, accounts: Accounts) -> Installation | None:
    """An installation that just gave the App access to an account it must not act on."""
    if event not in _GRANTS:
        return None
    try:
        parsed = _InstallationEvent.model_validate_json(body)
    except ValidationError as error:
        raise InvalidPayload(str(error.error_count())) from error
    if parsed.action != _GRANTS[event]:
        return None
    account = parsed.installation.account
    login = account.login if account else ""
    if accounts.may_act(login):
        return None
    return Installation(parsed.installation.id, login)


class _Delivery(_Model):
    installation: _Installation | None = None


def delivery_installation(body: str) -> int | None:
    """The installation a delivery comes from, or None for one that names none (`ping`)."""
    try:
        installation = _Delivery.model_validate_json(body).installation
    except ValidationError:
        return None
    return None if installation is None else installation.id
