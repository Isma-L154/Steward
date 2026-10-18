import json
from http import HTTPStatus
from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from steward.config import Config, MissingConfig, load_config
from steward.github.http import GitHubError
from steward.webhooks.events import (
    MAX_BODY_BYTES,
    InvalidPayload,
    pull_requests_to_evaluate,
    repos_to_audit,
)
from steward.webhooks.signature import is_valid_signature
from steward.worker.responses import error_response, json_response
from steward.worker.weekly_sweep import request_audit, run_weekly_sweep


class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Response:
        try:
            config = load_config(self.env)
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
        if path == "/webhook":
            if request.method != "POST":
                return error_response("method_not_allowed", HTTPStatus.METHOD_NOT_ALLOWED)
            return await self._webhook(request, config)
        return error_response("not_found", HTTPStatus.NOT_FOUND)

    async def _webhook(self, request: Any, config: Config) -> Response:
        client_ip = request.headers.get("CF-Connecting-IP") or "unknown"
        if not (await self.env.WEBHOOK_LIMIT.limit(key=client_ip)).success:
            return error_response("rate_limited", HTTPStatus.TOO_MANY_REQUESTS)
        # Only a body that declares a small enough length is read, so a large or unannounced
        # (chunked) one is never buffered.
        declared = request.headers.get("Content-Length")
        if declared is None or not declared.isdigit() or int(declared) > MAX_BODY_BYTES:
            return error_response("payload_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        body = await request.bytes()
        signature = request.headers.get("X-Hub-Signature-256")
        if not is_valid_signature(config.webhook_secret, body, signature):
            return error_response("invalid_signature", HTTPStatus.UNAUTHORIZED)
        event = request.headers.get("X-GitHub-Event") or ""
        if event == "ping":
            return json_response({"status": "pong"}, HTTPStatus.OK)
        try:
            text = body.decode("utf-8")
            pull_requests = pull_requests_to_evaluate(event, text)
            audits = repos_to_audit(event, text)
        except InvalidPayload, UnicodeDecodeError:
            return error_response("invalid_payload", HTTPStatus.BAD_REQUEST)
        # Awaited, not deferred: an evaluation takes a few seconds, well inside GitHub's
        # 10-second delivery timeout, and a deferred task could be cut off with the request.
        for pr in pull_requests:
            job = {
                "installation_id": pr.installation_id,
                "owner": pr.repo.owner,
                "name": pr.repo.name,
                "number": pr.number,
            }
            await self.env.MERGE_QUEUE.getByName(pr.repo.full_name).fetch(
                "https://queue/evaluate", method="POST", body=json.dumps(job)
            )
        # A push to main is also when other open updates fall behind it.
        for pushed in audits:
            job = {
                "installation_id": pushed.installation_id,
                "owner": pushed.repo.owner,
                "name": pushed.repo.name,
            }
            await self.env.MERGE_QUEUE.getByName(pushed.repo.full_name).fetch(
                "https://queue/evaluate-open", method="POST", body=json.dumps(job)
            )
            await request_audit(self.env, pushed.installation_id, pushed.repo)
        queued = len(pull_requests) + 2 * len(audits)
        return json_response({"queued": queued}, HTTPStatus.ACCEPTED)

    async def scheduled(self, controller: Any, env: Any, ctx: Any) -> None:
        try:
            audited = await run_weekly_sweep(self.env)
        except (MissingConfig, GitHubError) as error:
            print(f"weekly sweep failed: {error}")
            return
        print(f"weekly sweep audited {audited} repositories")
