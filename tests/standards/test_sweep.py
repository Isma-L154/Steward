from steward.github.http import GitHubError
from steward.github.models import InstalledRepo, RepoRef
from steward.standards.sweep import sweep

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

    assert await sweep([1, 2], _repositories, audit) == 3
    assert audited == [(1, "a"), (2, "b"), (2, "c")]


async def test_one_failing_audit_does_not_stop_the_others() -> None:
    audited: list[str] = []

    async def audit(installation: int, repo: RepoRef) -> None:
        if repo.name == "b":
            raise GitHubError(502, "/x")
        audited.append(repo.name)

    assert await sweep([1, 2], _repositories, audit) == 2
    assert audited == ["a", "c"]
