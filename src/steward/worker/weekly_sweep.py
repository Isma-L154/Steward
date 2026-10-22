import json
import time
from collections.abc import Sequence
from typing import Any

from steward.config import load_config
from steward.github.api import GitHubApi
from steward.github.app_auth import InstallationTokens, installations, uninstall
from steward.github.client import GitHubClient
from steward.github.models import Installation, InstalledRepo, RepoRef
from steward.standards.sweep import sweep
from steward.worker.fetch_http import WorkersFetch
from steward.worker.webcrypto import WebCryptoSigner


async def request_audit(env: Any, installation_id: int, repo: RepoRef) -> int:
    job = {"installation_id": installation_id, "owner": repo.owner, "name": repo.name}
    response = await env.STANDARDS_AUDIT.getByName(repo.full_name).fetch(
        "https://audit/audit", method="POST", body=json.dumps(job)
    )
    return int(response.status)


async def run_weekly_sweep(env: Any) -> int:
    """Audits every managed repository: a few GitHub calls here, one audit call per repository."""
    config = load_config(env)
    http = WorkersFetch()
    signer = WebCryptoSigner(config.private_key_pkcs8)
    tokens = InstallationTokens(http, config.app_id, signer, time.time)

    async def repositories(installation_id: int) -> Sequence[InstalledRepo]:
        api = GitHubApi(http, tokens, installation_id)
        return await GitHubClient(api).installed_repositories()

    async def audit(installation_id: int, repo: RepoRef) -> None:
        status = await request_audit(env, installation_id, repo)
        if status != 200:  # noqa: PLR2004 - the audit's "OK"
            raise RuntimeError(f"audit answered {status}")

    async def remove(installation: Installation) -> None:
        removed = await uninstall(http, config.app_id, signer, int(time.time()), installation)
        # The login comes from GitHub's listing: repr keeps it on one log line.
        print(f"installation {installation.id} of {installation.account!r}: removed={removed}")

    installed = await installations(http, config.app_id, signer, int(time.time()))
    return await sweep(installed, config.accounts, repositories, audit, remove)
