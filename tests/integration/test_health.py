import httpx
import pytest

from tests.integration.server import BASE_URL, TIMEOUT


@pytest.mark.integration
def test_health_reports_version() -> None:
    response = httpx.get(f"{BASE_URL}/health", timeout=TIMEOUT)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.integration
def test_unknown_path_is_404() -> None:
    assert httpx.get(f"{BASE_URL}/nope", timeout=TIMEOUT).status_code == 404


@pytest.mark.integration
def test_post_on_health_is_405() -> None:
    assert httpx.post(f"{BASE_URL}/health", timeout=TIMEOUT).status_code == 405
