from http import HTTPStatus
from typing import Any

from workers import Response

from steward.worker.headers import API_HEADERS


def json_response(body: dict[str, Any], status: HTTPStatus) -> Response:
    return Response.json(body, status=int(status), headers=dict(API_HEADERS))


def error_response(code: str, status: HTTPStatus) -> Response:
    return json_response({"error": code}, status)
