import re
from enum import StrEnum


class UpdateType(StrEnum):
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


_ORDER = (UpdateType.PATCH, UpdateType.MINOR, UpdateType.MAJOR)
_BLOCK = re.compile(r"^---$(.*?)^\.\.\.$", re.MULTILINE | re.DOTALL)
_ENTRY = re.compile(r"^- dependency-name:\s*(\S+)\s*$", re.MULTILINE)
_UPDATE_TYPE = re.compile(r"^\s+update-type:\s*(\S+)\s*$", re.MULTILINE)
_KNOWN = {f"version-update:semver-{kind.value}": kind for kind in UpdateType}
_SEMVER = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def classify(commit_message: str) -> UpdateType:
    """The largest update in Dependabot's metadata block; anything unclear counts as major."""
    block = _BLOCK.search(commit_message)
    if block is None:
        return UpdateType.MAJOR
    metadata = block.group(1)
    starts = list(_ENTRY.finditer(metadata))
    if not starts:
        return UpdateType.MAJOR
    kinds = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(metadata)
        stated = _UPDATE_TYPE.search(metadata, start.end(), end)
        if stated is not None:
            kinds.append(_KNOWN.get(stated.group(1), UpdateType.MAJOR))
        else:
            # Dependabot omits update-type for indirect dependencies; their versions are only
            # stated in the message ("Bumps [name](…) from A to B", "Updates `name` from A to B").
            kinds.append(_from_stated_versions(commit_message, start.group(1)))
    return max(kinds, key=_ORDER.index)


def _from_stated_versions(commit_message: str, name: str) -> UpdateType:
    escaped = re.escape(name)
    change = re.search(
        rf"(?:Bumps? \[?{escaped}\]?(?:\([^)\s]*\))?|Updates `{escaped}`)"
        r" from (\S+?) to (\S+?)\.?(?:\s|$)",
        commit_message,
    )
    if change is None:
        return UpdateType.MAJOR
    old, new = (_SEMVER.fullmatch(version) for version in change.groups())
    if old is None or new is None or old.group(1) != new.group(1):
        return UpdateType.MAJOR
    if old.group(2) != new.group(2):
        return UpdateType.MINOR
    return UpdateType.PATCH if old.group(3) != new.group(3) else UpdateType.MAJOR
