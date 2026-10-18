from typing import Any

from workers import DurableObject, Response


class MergeQueue(DurableObject):
    async def fetch(self, request: Any) -> Response:
        return Response("", status=404)
