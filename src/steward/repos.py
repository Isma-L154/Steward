from collections.abc import Sequence

IGNORE_TOPIC = "steward-ignore"


def is_managed(archived: bool, topics: Sequence[str]) -> bool:
    return not archived and IGNORE_TOPIC not in topics
