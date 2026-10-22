from steward.accounts import Accounts
from steward.github.http import GitHubError
from steward.github.models import Installation, InstalledRepo, RepoRef
from steward.standards.sweep import sweep

ACCOUNTS = Accounts.parse("o", "")
INSTALLATIONS = [Installation(1, "o"), Installation(2, "o")]
REPOS = {
    1: [
        InstalledRepo(RepoRef("o", "a"), archived=False, topics=()),
        InstalledRepo(RepoRef("o", "old"), archived=True, topics=()),
        InstalledRepo(RepoRef("o", "skip"), archived=False, topics=("steward-ignore",)),
    ],
    2: [
        InstalledRepo(RepoRef("o", "b"), archived=False, topics=("python",)),
        InstalledRepo(RepoRef("o", "c"), archived=False, topics=()),
    ],
}


async def _repositories(installation: int) -> list[InstalledRepo]:
    return REPOS[installation]


async def _no_audit(installation: int, repo: RepoRef) -> None:
    pass


class _Removals:
    def __init__(self) -> None:
        self.removed: list[int] = []

    async def __call__(self, installation: Installation) -> None:
        self.removed.append(installation.id)


async def test_every_managed_repository_is_audited_once() -> None:
    audited: list[tuple[int, str]] = []

    async def audit(installation: int, repo: RepoRef) -> None:
        audited.append((installation, repo.name))

    assert await sweep(INSTALLATIONS, ACCOUNTS, _repositories, audit, _Removals()) == 3
    assert audited == [(1, "a"), (2, "b"), (2, "c")]


async def test_one_failing_audit_does_not_stop_the_others() -> None:
    audited: list[str] = []

    async def audit(installation: int, repo: RepoRef) -> None:
        if repo.name == "b":
            raise GitHubError(502, "/x")
        audited.append(repo.name)

    assert await sweep(INSTALLATIONS, ACCOUNTS, _repositories, audit, _Removals()) == 2
    assert audited == ["a", "c"]


async def test_installations_of_unlisted_accounts_are_not_listed_or_audited() -> None:
    listed: list[int] = []

    async def repositories(installation: int) -> list[InstalledRepo]:
        listed.append(installation)
        return REPOS[installation]

    async def audit(installation: int, repo: RepoRef) -> None:
        raise AssertionError(repo)

    stranger = [Installation(2, "stranger")]
    assert await sweep(stranger, ACCOUNTS, repositories, audit, _Removals()) == 0
    assert listed == []


async def test_allowlisted_accounts_are_not_audited() -> None:
    async def audit(installation: int, repo: RepoRef) -> None:
        raise AssertionError(repo)

    allowed = Accounts.parse("o", "Wal-014")
    walter = [Installation(2, "Wal-014")]
    assert await sweep(walter, allowed, _repositories, audit, _Removals()) == 0


async def test_installations_of_unlisted_accounts_are_uninstalled() -> None:
    removals = _Removals()
    listed = [Installation(1, "o"), Installation(7, "stranger"), Installation(8, "")]

    await sweep(listed, ACCOUNTS, _repositories, _no_audit, removals)

    assert removals.removed == [7, 8]


async def test_allowed_installations_are_never_uninstalled() -> None:
    removals = _Removals()
    allowed = Accounts.parse("o", "Wal-014")
    listed = [Installation(1, "O"), Installation(2, "wal-014")]

    await sweep(listed, allowed, _repositories, _no_audit, removals)

    assert removals.removed == []


async def test_uninstalls_run_after_every_audit() -> None:
    # Removals must not spend the subrequests the owner's audits need first.
    events: list[str] = []

    async def audit(installation: int, repo: RepoRef) -> None:
        events.append(f"audit {repo.name}")

    async def remove(installation: Installation) -> None:
        events.append(f"remove {installation.id}")

    listed = [Installation(7, "stranger"), Installation(1, "o")]
    await sweep(listed, ACCOUNTS, _repositories, audit, remove)

    assert events == ["audit a", "remove 7"]


async def test_one_failing_uninstall_does_not_stop_the_others() -> None:
    removed: list[int] = []

    async def remove(installation: Installation) -> None:
        if installation.id == 7:
            raise GitHubError(502, "/app/installations/7")
        removed.append(installation.id)

    listed = [Installation(7, "x"), Installation(8, "y")]
    await sweep(listed, ACCOUNTS, _repositories, _no_audit, remove)

    assert removed == [8]
