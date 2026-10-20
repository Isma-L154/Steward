import json
from http import HTTPStatus
from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from steward.config import MissingConfig, load_config
from steward.hub.request import HUB_CALLER, check_caller, check_request
from steward.worker.responses import error_response, json_response


class HubApi(WorkerEntrypoint):
    """Reachable only through the hub's service binding: the custom domain serves `Default`."""

    async def fetch(self, request: Any) -> Response:
        try:
            load_config(self.env)
        except MissingConfig as error:
            print(f"configuration error: {error}")
            return error_response("misconfigured", HTTPStatus.INTERNAL_SERVER_ERROR)
        props = getattr(self.ctx, "props", None)
        rejection = check_caller(None if props is None else getattr(props, "caller", None))
        if rejection is not None:
            return error_response(rejection.code, rejection.status)
        if not (await self.env.HUB_LIMIT.limit(key=HUB_CALLER)).success:
            return error_response("rate_limited", HTTPStatus.TOO_MANY_REQUESTS)
        url = urlparse(request.url)
        length = request.headers.get("Content-Length")
        has_body = (length is not None and length != "0") or (
            request.headers.get("Transfer-Encoding") is not None
        )
        rejection = check_request(request.method, url.path, url.query, has_body)
        if rejection is not None:
            return error_response(rejection.code, rejection.status)
        route = url.path.removeprefix("/v1")
        response = await self.env.HUB_DATA.getByName("hub").fetch(f"https://hub{route}")
        return json_response(json.loads(await response.text()), HTTPStatus(int(response.status)))
