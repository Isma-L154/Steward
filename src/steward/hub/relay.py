import json
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any

_UNAVAILABLE = "github_unavailable"


async def relay(
    call: Callable[[], Awaitable[tuple[int, str]]],
) -> tuple[dict[str, Any], HTTPStatus]:
    """HubData's answer as the hub API returns it. Any failure of the call, or an answer that
    is not a JSON object with a known status, becomes 502 so the hub always gets the contract."""
    try:
        status, text = await call()
        body = json.loads(text)
        if not isinstance(body, dict):
            raise TypeError(type(body).__name__)
        return body, HTTPStatus(status)
    except Exception as error:
        # The type only: an exception's message may carry upstream content.
        print(f"hub data failed: {type(error).__name__}")
        return {"error": _UNAVAILABLE}, HTTPStatus.BAD_GATEWAY
