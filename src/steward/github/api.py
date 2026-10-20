import json
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from steward.github.app_auth import API, API_HEADERS, InstallationTokens
from steward.github.http import GitHubError, HttpClient, answer_detail, detail_from


class GitHubApi:
    """REST and GraphQL calls authenticated as one installation of the App."""

    def __init__(self, http: HttpClient, tokens: InstallationTokens, installation_id: int) -> None:
        self._http = http
        self._tokens = tokens
        self._installation_id = installation_id

    async def call(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        accept: frozenset[int] = frozenset({HTTPStatus.OK}),
    ) -> tuple[int, Any]:
        token = await self._tokens.token(self._installation_id)
        headers = {**API_HEADERS, "Authorization": f"Bearer {token}"}
        response = await self._http.request(
            method, f"{API}{path}", headers, None if body is None else json.dumps(body)
        )
        if response.status not in accept:
            raise GitHubError(
                response.status, path.split("?", maxsplit=1)[0], answer_detail(response.body)
            )
        return response.status, json.loads(response.body) if response.body else None

    async def get(self, path: str) -> Any:
        return (await self.call("GET", path))[1]

    async def graphql(self, query: str, variables: Mapping[str, Any]) -> Any:
        _, response = await self.call("POST", "/graphql", {"query": query, "variables": variables})
        # GraphQL reports failures in the body of a 200 answer.
        if response.get("errors"):
            raise GitHubError(HTTPStatus.OK, "/graphql", detail_from(response))
        return response["data"]

    async def graphql_partial(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        """The `data` of an answer that may carry `errors` for some fields; the fields that
        failed come back null."""
        _, response = await self.call("POST", "/graphql", {"query": query, "variables": variables})
        data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(data, dict):
            raise GitHubError(HTTPStatus.OK, "/graphql", detail_from(response))
        return data
