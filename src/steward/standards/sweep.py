from collections.abc import Awaitable, Callable, Sequence

from steward.accounts import Accounts
from steward.github.models import Installation, InstalledRepo, RepoRef
from steward.repos import is_managed


async def sweep(
    installations: Sequence[Installation],
    accounts: Accounts,
    repositories: Callable[[int], Awaitable[Sequence[InstalledRepo]]],
    audit: Callable[[int, RepoRef], Awaitable[None]],
) -> int:
    audited = 0
    for installation in installations:
        if not accounts.may_act(installation.account):
            continue
        for installed in await repositories(installation.id):
            if not is_managed(installed.archived, installed.topics):
                continue
            try:
                await audit(installation.id, installed.repo)
            except Exception as error:  # one repository must not stop the sweep
                print(f"{installed.repo.full_name}: audit failed: {error}")
                continue
            audited += 1
    return audited
