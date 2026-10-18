import json
from pathlib import Path
from typing import Any

import pytest

from steward.github.models import RepoRef
from steward.webhooks.events import InvalidPayload, PullRequestToEvaluate, pull_requests_to_evaluate

FIXTURE = Path(__file__).parent.parent / "fixtures" / "workflow_run_completed.json"


def _payload() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return payload


def test_completed_run_yields_its_dependabot_prs() -> None:
    body = json.dumps(_payload())
    assert pull_requests_to_evaluate("workflow_run", body) == [
        PullRequestToEvaluate(installation_id=42, repo=RepoRef("Isma-L154", "nextsode"), number=7)
    ]


def test_repo_full_name() -> None:
    assert RepoRef("Isma-L154", "nextsode").full_name == "Isma-L154/nextsode"


def test_non_dependabot_branches_are_skipped() -> None:
    payload = _payload()
    payload["workflow_run"]["pull_requests"][0]["head"]["ref"] = "feature/thing"
    assert pull_requests_to_evaluate("workflow_run", json.dumps(payload)) == []


def test_run_without_pull_requests_yields_nothing() -> None:
    payload = _payload()
    payload["workflow_run"]["pull_requests"] = []
    assert pull_requests_to_evaluate("workflow_run", json.dumps(payload)) == []


def test_requested_run_yields_nothing() -> None:
    payload = _payload()
    payload["action"] = "requested"
    assert pull_requests_to_evaluate("workflow_run", json.dumps(payload)) == []


@pytest.mark.parametrize("event", ["push", "ping", "pull_request", "installation"])
def test_other_events_yield_nothing(event: str) -> None:
    assert pull_requests_to_evaluate(event, json.dumps(_payload())) == []


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "[]",
        '{"action":"completed"}',
        '{"action":"completed","installation":{"id":"42"}}',
    ],
)
def test_malformed_completed_run_raises(body: str) -> None:
    with pytest.raises(InvalidPayload):
        pull_requests_to_evaluate("workflow_run", body)


def test_string_installation_id_is_rejected_not_coerced() -> None:
    payload = _payload()
    payload["installation"]["id"] = "42"
    with pytest.raises(InvalidPayload):
        pull_requests_to_evaluate("workflow_run", json.dumps(payload))
