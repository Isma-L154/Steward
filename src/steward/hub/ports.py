from typing import Any, Protocol


class HubStore(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def put(self, key: str, value: dict[str, Any]) -> None: ...
