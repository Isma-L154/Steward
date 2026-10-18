import hashlib
import hmac
import http.client
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

from steward.webhooks.events import MAX_BODY_BYTES
from tests.integration.server import BASE_URL, TIMEOUT

SECRET = os.environ.get("STEWARD_WEBHOOK_SECRET", "ci-webhook-secret").encode()
FIXTURE = Path(__file__).parent.parent / "fixtures" / "workflow_run_completed.json"

pytestmark = pytest.mark.integration


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def _post(body: bytes, event: str, signature: str | None = None) -> httpx.Response:
    headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return httpx.post(f"{BASE_URL}/webhook", content=body, headers=headers, timeout=TIMEOUT)


def test_unsigned_webhook_is_401() -> None:
    assert _post(b"{}", "ping").status_code == 401


def test_wrongly_signed_webhook_is_401() -> None:
    assert _post(b"{}", "ping", "sha256=" + "0" * 64).status_code == 401


def test_signed_ping_is_200() -> None:
    body = b'{"zen":"Keep it logically awesome."}'
    response = _post(body, "ping", _sign(body))
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"


def _status_for_declared_length(length: int | None) -> int:
    """Declares a length without sending that many bytes: the size check must not read them."""
    url = urlparse(BASE_URL)
    connection = http.client.HTTPConnection(url.hostname or "localhost", url.port, timeout=TIMEOUT)
    connection.putrequest("POST", "/webhook")
    connection.putheader("X-GitHub-Event", "ping")
    if length is None:
        connection.putheader("Transfer-Encoding", "chunked")
    else:
        connection.putheader("Content-Length", str(length))
    connection.endheaders()
    connection.send(b"0\r\n\r\n" if length is None else b"{}")
    status = connection.getresponse().status
    connection.close()
    return status


def test_body_declared_over_limit_is_413() -> None:
    assert _status_for_declared_length(MAX_BODY_BYTES + 1) == 413


def test_body_without_declared_length_is_413() -> None:
    assert _status_for_declared_length(None) == 413


def test_signed_malformed_workflow_run_is_400() -> None:
    body = b'{"action":"completed"}'
    assert _post(body, "workflow_run", _sign(body)).status_code == 400


def test_signed_workflow_run_for_feature_branch_is_202_with_nothing_queued() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["workflow_run"]["pull_requests"][0]["head"]["ref"] = "feature/thing"
    body = json.dumps(payload).encode()
    response = _post(body, "workflow_run", _sign(body))
    assert response.status_code == 202
    assert response.json() == {"queued": 0}


def test_get_on_webhook_is_405() -> None:
    assert httpx.get(f"{BASE_URL}/webhook", timeout=TIMEOUT).status_code == 405


def test_signed_workflow_run_for_dependabot_branch_queues_one_evaluation() -> None:
    body = FIXTURE.read_bytes()
    response = _post(body, "workflow_run", _sign(body))
    assert response.status_code == 202
    assert response.json() == {"queued": 1}


def test_rate_limit_answers_429_after_120_requests_in_a_minute_from_one_ip() -> None:
    # The limiter counts in fixed 60-second windows: 241 requests put more than 120 in one
    # of at most two windows, wherever the minute boundary falls.
    ip = f"203.0.113.{secrets.randbelow(254) + 1}"  # documentation range, a fresh quota
    headers = {"X-GitHub-Event": "ping", "CF-Connecting-IP": ip}
    statuses: list[int] = []
    with httpx.Client(timeout=TIMEOUT) as client:
        for _ in range(241):
            statuses.append(
                client.post(f"{BASE_URL}/webhook", content=b"{}", headers=headers).status_code
            )
            if statuses[-1] == 429:
                break
    assert statuses[-1] == 429
    assert 401 in statuses
