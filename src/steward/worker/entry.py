from http import HTTPStatus
from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from steward.config import MissingConfig, load_config
from steward.worker.responses import error_response, json_response


class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Response:
        try:
            load_config(self.env)
        except MissingConfig as error:
            print(f"configuration error: {error}")
            return error_response("misconfigured", HTTPStatus.INTERNAL_SERVER_ERROR)
        path = urlparse(request.url).path
        if path == "/health":
            if request.method != "GET":
                return error_response("method_not_allowed", HTTPStatus.METHOD_NOT_ALLOWED)
            # The deploy sets BUILD_VERSION to the commit, so CI can wait for this exact build.
            version = getattr(self.env, "BUILD_VERSION", None) or "dev"
            return json_response({"status": "ok", "version": str(version)}, HTTPStatus.OK)
        return error_response("not_found", HTTPStatus.NOT_FOUND)
