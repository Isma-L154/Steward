import httpx
import pytest

from tests.integration.server import BASE_URL, TIMEOUT


@pytest.mark.integration
@pytest.mark.parametrize("path", ["/v1/health", "/v1/report"])
def test_hub_routes_are_not_public(path: str) -> None:
    response = httpx.get(f"{BASE_URL}{path}", timeout=TIMEOUT)
    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}
    assert response.headers["cache-control"] == "no-store"
