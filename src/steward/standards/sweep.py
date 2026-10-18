from collections.abc import Awaitable, Callable, Sequence

from steward.github.models import RepoRef
from steward.github.standards_client import InstalledRepo
from steward.repos import is_managed


async def sweep(
    installations: Sequence[int],
    repositories: Callable[[int], Awaitable[Sequence[InstalledRepo]]],
    audit: Callable[[int, RepoRef], Awaitable[None]],
) -> int:
    audited = 0
    for installation in installations:
        for installed in await repositories(installation):
            if not is_managed(installed.archived, installed.topics):
                continue
            try:
                await audit(installation, installed.repo)
            except Exception as error:  # one repository must not stop the sweep
                print(f"{installed.repo.full_name}: audit failed: {error}")
                continue
            audited += 1
    return audited
