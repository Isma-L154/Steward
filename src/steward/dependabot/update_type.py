import re
from enum import StrEnum


class UpdateType(StrEnum):
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


_ORDER = (UpdateType.PATCH, UpdateType.MINOR, UpdateType.MAJOR)
_BLOCK = re.compile(r"^---$(.*?)^\.\.\.$", re.MULTILINE | re.DOTALL)
_ENTRY = re.compile(r"^- dependency-name:", re.MULTILINE)
_UPDATE_TYPE = re.compile(r"^\s+update-type:\s*(\S+)\s*$", re.MULTILINE)
_KNOWN = {f"version-update:semver-{kind.value}": kind for kind in UpdateType}


def classify(commit_message: str) -> UpdateType:
    """The largest update in Dependabot's metadata block; anything unclear counts as major."""
    block = _BLOCK.search(commit_message)
    if block is None:
        return UpdateType.MAJOR
    entries = len(_ENTRY.findall(block.group(1)))
    kinds = [_KNOWN.get(value) for value in _UPDATE_TYPE.findall(block.group(1))]
    if entries == 0 or len(kinds) != entries:
        return UpdateType.MAJOR
    largest = UpdateType.PATCH
    for kind in kinds:
        if kind is None:
            return UpdateType.MAJOR
        largest = max(largest, kind, key=_ORDER.index)
    return largest
