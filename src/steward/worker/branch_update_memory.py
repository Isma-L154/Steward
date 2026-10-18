from typing import Any

from steward.github.models import RepoRef


class DurableObjectBranchUpdateMemory:
    """Kept in the repository's own MergeQueue storage, so keys need no repo prefix."""

    def __init__(self, storage: Any) -> None:
        self._storage = storage

    async def was_requested(self, repo: RepoRef, number: int, head_sha: str) -> bool:
        return bool(await self._storage.get(f"branch-update:{number}:{head_sha}"))

    async def remember(self, repo: RepoRef, number: int, head_sha: str) -> None:
        await self._storage.put(f"branch-update:{number}:{head_sha}", True)
