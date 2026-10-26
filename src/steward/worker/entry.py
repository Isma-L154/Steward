import json
import time
from http import HTTPStatus
from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from steward.config import Config, MissingConfig, load_config
from steward.github.app_auth import uninstall
from steward.github.http import GitHubError
from steward.github.models import Installation
from steward.webhooks.events import (
    InvalidPayload,
    delivery_installation,
    installation_to_remove,
    is_acceptable_length,
    pull_requests_to_evaluate,
    pushes_to_default,
)
from steward.webhooks.signature import is_valid_signature
from steward.worker.fetch_http import WorkersFetch
from steward.worker.responses import error_response, json_response
from steward.worker.webcrypto import WebCryptoSigner
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
        if not is_acceptable_length(request.headers.get("Content-Length")):
            return error_response("payload_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        body = await request.bytes()
        signature = request.headers.get("X-Hub-Signature-256")
        if not is_valid_signature(config.webhook_secret, body, signature):
            return error_response("invalid_signature", HTTPStatus.UNAUTHORIZED)
        event = request.headers.get("X-GitHub-Event") or ""
        if event == "ping":
            return json_response({"status": "pong"}, HTTPStatus.OK)
        return await self._handle(config, event, body)

    async def _handle(self, config: Config, event: str, body: bytes) -> Response:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return error_response("invalid_payload", HTTPStatus.BAD_REQUEST)
        installation = delivery_installation(text)
        if (
            installation is not None
            and not (await self.env.INSTALLATION_LIMIT.limit(key=str(installation))).success
        ):
            return error_response("rate_limited", HTTPStatus.TOO_MANY_REQUESTS)
        try:
            removal = installation_to_remove(event, text, config.accounts)
            pull_requests = pull_requests_to_evaluate(event, text, config.accounts)
            pushes = pushes_to_default(event, text, config.accounts)
        except InvalidPayload:
            return error_response("invalid_payload", HTTPStatus.BAD_REQUEST)
        if removal is not None:
            return await self._uninstall(config, removal)
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
        for pushed in pushes:
            job = {
                "installation_id": pushed.installation_id,
                "owner": pushed.repo.owner,
                "name": pushed.repo.name,
            }
            await self.env.MERGE_QUEUE.getByName(pushed.repo.full_name).fetch(
                "https://queue/evaluate-open", method="POST", body=json.dumps(job)
            )
            if pushed.audit:
                await request_audit(self.env, pushed.installation_id, pushed.repo)
        queued = len(pull_requests) + sum(1 + pushed.audit for pushed in pushes)
        return json_response({"queued": queued}, HTTPStatus.ACCEPTED)

    async def _uninstall(self, config: Config, installation: Installation) -> Response:
        signer = WebCryptoSigner(config.private_key_pkcs8)
        try:
            removed = await uninstall(
                WorkersFetch(), config.app_id, signer, int(time.time()), installation
            )
        except GitHubError as error:
            print(f"installation {installation.id}: {error}")
            return error_response("github_error", HTTPStatus.BAD_GATEWAY)
        # The login comes from the payload: repr keeps it on one log line.
        print(f"installation {installation.id} of {installation.account!r}: removed={removed}")
        return json_response({"uninstalled": removed}, HTTPStatus.ACCEPTED)

    async def scheduled(self, controller: Any, env: Any, ctx: Any) -> None:
        try:
            audited = await run_weekly_sweep(self.env)
            print(f"weekly sweep audited {audited} repositories")
        except Exception as error:
            print(f"weekly sweep failed: {type(error).__name__}: {error}")
        # The report reads GitHub's current state, so it is built even after a failed sweep.
        try:
            report = await self.env.HUB_DATA.getByName("hub").fetch(
                "https://hub/build-report", method="POST"
            )
            print(f"weekly report answered {report.status}")
        except Exception as error:
            # The type only, as at the hub API boundary: the message may carry upstream content.
            print(f"weekly report failed: {type(error).__name__}")
