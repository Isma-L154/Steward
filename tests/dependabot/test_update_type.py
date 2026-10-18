from steward.dependabot.update_type import UpdateType, classify


def _message(*entries: tuple[str, str | None]) -> str:
    lines = ["Bump the python group with updates", "", "---", "updated-dependencies:"]
    for name, update_type in entries:
        lines += [
            f"- dependency-name: {name}",
            "  dependency-version: 1.2.3",
            "  dependency-type: direct:production",
        ]
        if update_type is not None:
            lines.append(f"  update-type: {update_type}")
    lines += ["...", "", "Signed-off-by: dependabot[bot] <support@github.com>"]
    return "\n".join(lines)


PATCH = "version-update:semver-patch"
MINOR = "version-update:semver-minor"
MAJOR = "version-update:semver-major"


def test_single_minor() -> None:
    assert classify(_message(("httpx", MINOR))) == UpdateType.MINOR


def test_single_patch() -> None:
    assert classify(_message(("httpx", PATCH))) == UpdateType.PATCH


def test_single_major() -> None:
    assert classify(_message(("httpx", MAJOR))) == UpdateType.MAJOR


def test_group_takes_the_largest() -> None:
    assert classify(_message(("a", PATCH), ("b", MAJOR), ("c", MINOR))) == UpdateType.MAJOR


def test_group_of_minor_and_patch_is_minor() -> None:
    assert classify(_message(("a", PATCH), ("b", MINOR))) == UpdateType.MINOR


def test_no_metadata_is_major() -> None:
    assert classify("Bump x from 1 to 2") == UpdateType.MAJOR


def test_empty_dependency_list_is_major() -> None:
    assert classify("Bump\n\n---\nupdated-dependencies: []\n...\n") == UpdateType.MAJOR


def test_entry_without_update_type_makes_it_major() -> None:
    assert classify(_message(("a", PATCH), ("b", None))) == UpdateType.MAJOR


def test_unknown_update_type_is_major() -> None:
    assert classify(_message(("a", "version-update:semver-weird"))) == UpdateType.MAJOR


def test_metadata_outside_the_block_is_ignored() -> None:
    message = "Bump a\n\nupdate-type: version-update:semver-patch\ndependency-name: a\n"
    assert classify(message) == UpdateType.MAJOR
