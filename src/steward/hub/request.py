from dataclasses import dataclass
from http import HTTPStatus

HUB_CALLER = "hub"
ROUTES = frozenset({"/v1/health", "/v1/report"})


@dataclass(frozen=True)
class Rejection:
    status: HTTPStatus
    code: str


def check_caller(caller: object) -> Rejection | None:
    """The caller comes from the service binding's `props`, which only the account's
    deployers can set; anything but the hub's exact value is refused."""
    if caller == HUB_CALLER and isinstance(caller, str):
        return None
    return Rejection(HTTPStatus.FORBIDDEN, "forbidden")


def check_request(method: str, path: str, query: str, has_body: bool) -> Rejection | None:
    if method != "GET":
        return Rejection(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed")
    if query or has_body:
        return Rejection(HTTPStatus.BAD_REQUEST, "invalid_request")
    if path not in ROUTES:
        return Rejection(HTTPStatus.NOT_FOUND, "not_found")
    return None
