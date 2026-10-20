import json
from http import HTTPStatus

import pytest

from steward.hub.relay import relay

UNAVAILABLE = ({"error": "github_unavailable"}, HTTPStatus.BAD_GATEWAY)


async def test_answer_is_passed_through() -> None:
    async def call() -> tuple[int, str]:
        return 200, json.dumps({"repos": []})

    assert await relay(call) == ({"repos": []}, HTTPStatus.OK)


async def test_documented_error_is_passed_through() -> None:
    async def call() -> tuple[int, str]:
        return 500, json.dumps({"error": "misconfigured"})

    assert await relay(call) == ({"error": "misconfigured"}, HTTPStatus.INTERNAL_SERVER_ERROR)


async def test_a_failed_call_is_github_unavailable_and_logs_only_its_type(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def call() -> tuple[int, str]:
        raise KeyError("ghs_secret upstream content")

    assert await relay(call) == UNAVAILABLE
    logged = capsys.readouterr().out
    assert "KeyError" in logged
    assert "ghs_secret" not in logged


@pytest.mark.parametrize(
    ("status", "text"),
    [
        (500, "Internal Server Error"),
        (200, "[1, 2]"),
        (200, ""),
        (999, json.dumps({"repos": []})),
    ],
)
async def test_an_answer_outside_the_contract_is_github_unavailable(status: int, text: str) -> None:
    async def call() -> tuple[int, str]:
        return status, text

    assert await relay(call) == UNAVAILABLE
