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


async def test_every_managed_repository_is_audited_once() -> None:
    audited: list[tuple[int, str]] = []

    async def audit(installation: int, repo: RepoRef) -> None:
        audited.append((installation, repo.name))

    assert await sweep(INSTALLATIONS, ACCOUNTS, _repositories, audit) == 3
    assert audited == [(1, "a"), (2, "b"), (2, "c")]


async def test_one_failing_audit_does_not_stop_the_others() -> None:
    audited: list[str] = []

    async def audit(installation: int, repo: RepoRef) -> None:
        if repo.name == "b":
            raise GitHubError(502, "/x")
        audited.append(repo.name)

    assert await sweep(INSTALLATIONS, ACCOUNTS, _repositories, audit) == 2
    assert audited == ["a", "c"]


async def test_installations_of_unlisted_accounts_are_not_listed_or_audited() -> None:
    listed: list[int] = []

    async def repositories(installation: int) -> list[InstalledRepo]:
        listed.append(installation)
        return REPOS[installation]

    async def audit(installation: int, repo: RepoRef) -> None:
        raise AssertionError(repo)

    assert await sweep([Installation(2, "stranger")], ACCOUNTS, repositories, audit) == 0
    assert listed == []


async def test_allowlisted_accounts_are_not_audited() -> None:
    async def audit(installation: int, repo: RepoRef) -> None:
        raise AssertionError(repo)

    allowed = Accounts.parse("o", "Wal-014")
    assert await sweep([Installation(2, "Wal-014")], allowed, _repositories, audit) == 0
