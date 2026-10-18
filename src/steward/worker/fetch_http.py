from collections.abc import Mapping

from workers import fetch

from steward.github.http import HttpResponse


class WorkersFetch:
    """HttpClient over the Workers runtime's fetch."""

    async def request(
        self, method: str, url: str, headers: Mapping[str, str], body: str | None = None
    ) -> HttpResponse:
        response = await fetch(url, method=method, headers=dict(headers), body=body)
        return HttpResponse(int(response.status), await response.text())
