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


def _indirect(name: str, intro: str) -> str:
    return (
        f"chore(deps-dev): Bump {name}\n\n{intro}\n\n---\nupdated-dependencies:\n"
        f"- dependency-name: {name}\n  dependency-version: 9.9.9\n  dependency-type: indirect\n"
        "...\n\nSigned-off-by: dependabot[bot] <support@github.com>"
    )


def test_indirect_patch_comes_from_the_stated_versions() -> None:
    intro = "Bumps [source-map-js](https://github.com/7rulnik/source-map-js) from 1.2.1 to 1.2.2."
    assert classify(_indirect("source-map-js", intro)) == UpdateType.PATCH


def test_indirect_minor_from_a_plain_bump_line() -> None:
    assert classify(_indirect("lodash", "Bump lodash from 4.17.21 to 4.18.0")) == UpdateType.MINOR


def test_indirect_with_v_prefixed_versions() -> None:
    intro = "Bumps [a](https://x) from v2.3.0 to v2.3.4."
    assert classify(_indirect("a", intro)) == UpdateType.PATCH


def test_indirect_major_change_is_major() -> None:
    assert classify(_indirect("a", "Bumps [a](https://x) from 1.9.0 to 2.0.0.")) == UpdateType.MAJOR


def test_indirect_without_stated_versions_is_major() -> None:
    assert classify(_indirect("a", "Bumps a.")) == UpdateType.MAJOR


def test_indirect_versions_of_another_dependency_do_not_count() -> None:
    assert classify(_indirect("a", "Bumps [b](https://x) from 1.0.0 to 1.0.1.")) == UpdateType.MAJOR


def test_indirect_unparseable_version_is_major() -> None:
    intro = "Bumps [a](https://x) from 1.0.0-beta.1 to 1.0.0."
    assert classify(_indirect("a", intro)) == UpdateType.MAJOR


def test_indirect_entry_in_a_group_uses_its_updates_line() -> None:
    message = (
        "Bumps the toolchain group with 2 updates\n\n"
        "Updates `vite` from 7.1.2 to 7.1.9\n"
        "Updates `rollup` from 4.50.0 to 4.52.3\n\n"
        "---\nupdated-dependencies:\n"
        "- dependency-name: vite\n  dependency-version: 7.1.9\n"
        "  update-type: version-update:semver-patch\n"
        "- dependency-name: rollup\n  dependency-version: 4.52.3\n  dependency-type: indirect\n"
        "...\n"
    )
    assert classify(message) == UpdateType.MINOR
