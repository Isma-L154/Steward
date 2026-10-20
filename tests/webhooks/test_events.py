import json
from pathlib import Path
from typing import Any

import pytest

from steward.accounts import Accounts
from steward.github.models import Installation, RepoRef
from steward.webhooks.events import (
    InvalidPayload,
    PullRequestToEvaluate,
    PushToDefault,
    delivery_installation,
    installation_to_remove,
    pull_requests_to_evaluate,
    pushes_to_default,
)

ACCOUNTS = Accounts.parse("Isma-L154", "Wal-014")
FIXTURE = Path(__file__).parent.parent / "fixtures" / "workflow_run_completed.json"


def _payload() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return payload


def test_completed_run_yields_its_dependabot_prs() -> None:
    body = json.dumps(_payload())
    assert pull_requests_to_evaluate("workflow_run", body, ACCOUNTS) == [
        PullRequestToEvaluate(installation_id=42, repo=RepoRef("Isma-L154", "nextsode"), number=7)
    ]


def test_repo_full_name() -> None:
    assert RepoRef("Isma-L154", "nextsode").full_name == "Isma-L154/nextsode"


def test_non_dependabot_branches_are_skipped() -> None:
    payload = _payload()
    payload["workflow_run"]["pull_requests"][0]["head"]["ref"] = "feature/thing"
    assert pull_requests_to_evaluate("workflow_run", json.dumps(payload), ACCOUNTS) == []


def test_run_without_pull_requests_yields_nothing() -> None:
    payload = _payload()
    payload["workflow_run"]["pull_requests"] = []
    assert pull_requests_to_evaluate("workflow_run", json.dumps(payload), ACCOUNTS) == []


def test_requested_run_yields_nothing() -> None:
    payload = _payload()
    payload["action"] = "requested"
    assert pull_requests_to_evaluate("workflow_run", json.dumps(payload), ACCOUNTS) == []


@pytest.mark.parametrize("event", ["push", "ping", "pull_request", "installation"])
def test_other_events_yield_nothing(event: str) -> None:
    assert pull_requests_to_evaluate(event, json.dumps(_payload()), ACCOUNTS) == []


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
        pull_requests_to_evaluate("workflow_run", body, ACCOUNTS)


def test_string_installation_id_is_rejected_not_coerced() -> None:
    payload = _payload()
    payload["installation"]["id"] = "42"
    with pytest.raises(InvalidPayload):
        pull_requests_to_evaluate("workflow_run", json.dumps(payload), ACCOUNTS)


PUSH_FIXTURE = Path(__file__).parent.parent / "fixtures" / "push_main.json"


def _push() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(PUSH_FIXTURE.read_text(encoding="utf-8"))
    return payload


def test_push_to_the_default_branch_is_audited() -> None:
    assert pushes_to_default("push", json.dumps(_push()), ACCOUNTS) == [
        PushToDefault(installation_id=42, repo=RepoRef("Isma-L154", "nextsode"), audit=True)
    ]


def test_push_to_another_branch_is_not_audited() -> None:
    payload = _push()
    payload["ref"] = "refs/heads/feature/x"
    assert pushes_to_default("push", json.dumps(payload), ACCOUNTS) == []


def test_push_to_an_ignored_repository_is_not_audited() -> None:
    payload = _push()
    payload["repository"]["topics"] = ["steward-ignore"]
    assert pushes_to_default("push", json.dumps(payload), ACCOUNTS) == []


def test_push_to_an_archived_repository_is_not_audited() -> None:
    payload = _push()
    payload["repository"]["archived"] = True
    assert pushes_to_default("push", json.dumps(payload), ACCOUNTS) == []


def test_push_without_topics_or_archived_is_audited() -> None:
    payload = _push()
    del payload["repository"]["topics"]
    del payload["repository"]["archived"]
    assert len(pushes_to_default("push", json.dumps(payload), ACCOUNTS)) == 1


def test_push_without_default_branch_is_invalid() -> None:
    payload = _push()
    del payload["repository"]["default_branch"]
    with pytest.raises(InvalidPayload):
        pushes_to_default("push", json.dumps(payload), ACCOUNTS)


def test_other_events_are_not_audited() -> None:
    assert pushes_to_default("workflow_run", json.dumps(_payload()), ACCOUNTS) == []


def test_workflow_run_in_an_ignored_repository_yields_nothing() -> None:
    payload = _payload()
    payload["repository"]["topics"] = ["steward-ignore"]
    assert pull_requests_to_evaluate("workflow_run", json.dumps(payload), ACCOUNTS) == []


def test_workflow_run_from_an_unlisted_account_is_ignored() -> None:
    payload = _payload()
    payload["repository"]["owner"]["login"] = "stranger"
    assert pull_requests_to_evaluate("workflow_run", json.dumps(payload), ACCOUNTS) == []


def test_workflow_run_from_an_allowlisted_account_is_evaluated() -> None:
    payload = _payload()
    payload["repository"]["owner"]["login"] = "Wal-014"
    assert len(pull_requests_to_evaluate("workflow_run", json.dumps(payload), ACCOUNTS)) == 1


def test_push_from_an_unlisted_account_is_ignored() -> None:
    payload = _push()
    payload["repository"]["owner"]["login"] = "stranger"
    assert pushes_to_default("push", json.dumps(payload), ACCOUNTS) == []


def _installation(event_action: str, login: str | None) -> str:
    account = None if login is None else {"login": login}
    return json.dumps({"action": event_action, "installation": {"id": 9, "account": account}})


@pytest.mark.parametrize("event", ["installation", "installation_repositories"])
def test_new_installation_from_an_unlisted_account_is_removed(event: str) -> None:
    action = "created" if event == "installation" else "added"
    body = _installation(action, "stranger")
    assert installation_to_remove(event, body, ACCOUNTS) == Installation(9, "stranger")


@pytest.mark.parametrize("login", ["Isma-L154", "wal-014"])
def test_new_installation_from_a_listed_account_is_kept(login: str) -> None:
    assert installation_to_remove("installation", _installation("created", login), ACCOUNTS) is None


@pytest.mark.parametrize("action", ["deleted", "suspend", "removed"])
def test_other_installation_actions_remove_nothing(action: str) -> None:
    assert (
        installation_to_remove("installation", _installation(action, "stranger"), ACCOUNTS) is None
    )


def test_installation_without_an_account_is_removed() -> None:
    assert installation_to_remove("installation", _installation("created", None), ACCOUNTS) == (
        Installation(9, "")
    )


def test_other_events_remove_nothing() -> None:
    assert installation_to_remove("push", json.dumps(_push()), ACCOUNTS) is None


def test_malformed_installation_event_is_invalid() -> None:
    with pytest.raises(InvalidPayload):
        installation_to_remove("installation", json.dumps({"action": "created"}), ACCOUNTS)


def test_push_from_an_allowlisted_account_is_not_audited() -> None:
    payload = _push()
    payload["repository"]["owner"]["login"] = "Wal-014"
    assert pushes_to_default("push", json.dumps(payload), ACCOUNTS) == [
        PushToDefault(installation_id=42, repo=RepoRef("Wal-014", "nextsode"), audit=False)
    ]


def test_delivery_installation_is_read_from_any_event() -> None:
    assert delivery_installation(json.dumps(_push())) == 42
    assert delivery_installation(json.dumps(_payload())) == 42
    assert delivery_installation(_installation("created", "stranger")) == 9


@pytest.mark.parametrize(
    "body", ['{"zen": "Keep it logically awesome."}', '{"installation": null}', "[]", "not json"]
)
def test_delivery_without_an_installation_has_none(body: str) -> None:
    assert delivery_installation(body) is None
