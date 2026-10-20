import httpx
import pytest

from tests.integration.server import BASE_URL, CALLER_URL, TIMEOUT

# The hub's per-minute budget (HUB_LIMIT in wrangler.toml).
HUB_LIMIT = 60
SECURITY_HEADERS = {
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "strict-transport-security": "max-age=63072000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


def _call(binding: str, path: str, method: str = "GET") -> httpx.Response:
    return httpx.request(method, f"{CALLER_URL}/{binding}{path}", timeout=TIMEOUT)


def _assert_api_answer(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json() == {"error": code}
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value


@pytest.mark.integration
@pytest.mark.parametrize("path", ["/v1/health", "/v1/report"])
def test_hub_routes_are_not_public(path: str) -> None:
    response = httpx.get(f"{BASE_URL}{path}", timeout=TIMEOUT)
    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.integration
@pytest.mark.parametrize("path", ["/v1/health", "/v1/report"])
def test_binding_with_props_reaches_the_data(path: str) -> None:
    # The throwaway secrets make every GitHub call fail, so the data path answers 502.
    _assert_api_answer(_call("with-props", path), 502, "github_unavailable")


@pytest.mark.integration
def test_binding_without_props_is_forbidden() -> None:
    _assert_api_answer(_call("no-props", "/v1/health"), 403, "forbidden")


@pytest.mark.integration
def test_query_string_is_refused() -> None:
    _assert_api_answer(_call("with-props", "/v1/health?refresh=1"), 400, "invalid_request")


@pytest.mark.integration
def test_other_method_is_refused() -> None:
    _assert_api_answer(_call("with-props", "/v1/health", "POST"), 405, "method_not_allowed")


@pytest.mark.integration
def test_other_path_is_not_found() -> None:
    _assert_api_answer(_call("with-props", "/v1/nope"), 404, "not_found")


@pytest.mark.integration
def test_calls_past_the_limit_are_rate_limited() -> None:
    # Last in the file: it spends the rest of the budget. The query string makes each call stop
    # at the request check, after the limit, without reaching GitHub. The limit counts in fixed
    # one-minute windows, so a burst can straddle two; within twice the budget plus one call,
    # one window must go over.
    answers: list[httpx.Response] = []
    with httpx.Client(base_url=f"{CALLER_URL}/with-props", timeout=TIMEOUT) as client:
        while len(answers) <= 2 * HUB_LIMIT:
            answers.append(client.get(f"/v1/health?n={len(answers)}"))
            if answers[-1].status_code == httpx.codes.TOO_MANY_REQUESTS:
                break
    assert {answer.status_code for answer in answers[:-1]} == {400}
    _assert_api_answer(answers[-1], 429, "rate_limited")
