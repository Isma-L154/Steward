from http import HTTPStatus

import pytest

from steward.hub.request import HUB_CALLER, ROUTES, Rejection, check_caller, check_request

FORBIDDEN = Rejection(HTTPStatus.FORBIDDEN, "forbidden")
NOT_FOUND = Rejection(HTTPStatus.NOT_FOUND, "not_found")
INVALID = Rejection(HTTPStatus.BAD_REQUEST, "invalid_request")


def test_constants() -> None:
    assert HUB_CALLER == "hub"
    assert frozenset({"/v1/health", "/v1/report"}) == ROUTES


def test_caller_must_be_hub() -> None:
    assert check_caller("hub") is None


@pytest.mark.parametrize("caller", [None, "", "Hub", "other", {"caller": "hub"}, b"hub"])
def test_any_other_caller_is_forbidden(caller: object) -> None:
    assert check_caller(caller) == FORBIDDEN


@pytest.mark.parametrize(
    ("method", "path", "query", "has_body", "expected"),
    [
        (
            "POST",
            "/v1/health",
            "",
            False,
            Rejection(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed"),
        ),
        (
            "POST",
            "/nope",
            "x=1",
            True,
            Rejection(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed"),
        ),
        ("GET", "/v1/health", "repo=x", False, INVALID),
        ("GET", "/v1/health", "", True, INVALID),
        ("GET", "/v1/../health", "", False, NOT_FOUND),
        ("GET", "/v1/health/", "", False, NOT_FOUND),
        ("GET", "/health", "", False, NOT_FOUND),
        ("GET", "/V1/HEALTH", "", False, NOT_FOUND),
        ("GET", "/v1/health", "", False, None),
        ("GET", "/v1/report", "", False, None),
    ],
)
def test_method_query_body_path_in_order(
    method: str, path: str, query: str, has_body: bool, expected: Rejection | None
) -> None:
    assert check_request(method, path, query, has_body) == expected
