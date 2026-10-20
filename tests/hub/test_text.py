from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from steward.github.models import RepoRef
from steward.hub.text import (
    MAX_TITLE,
    URL_PATTERN,
    clean_title,
    is_safe_repo,
    iso,
    issue_url,
    pull_url,
    repo_url,
    unchecked_findings,
)

_owners = st.from_regex(r"[A-Za-z0-9-]{1,39}", fullmatch=True)
_names = st.from_regex(r"[A-Za-z0-9._-]{1,100}", fullmatch=True).filter(
    lambda name: name not in {".", ".."}
)


@given(_owners, _names, st.integers(min_value=1, max_value=10**9))
def test_built_urls_match_the_pattern(owner: str, name: str, number: int) -> None:
    repo = RepoRef(owner, name)
    assert is_safe_repo(repo)
    for url in (repo_url(repo), pull_url(repo, number), issue_url(repo, number)):
        assert URL_PATTERN.fullmatch(url)


@pytest.mark.parametrize(
    "repo",
    [
        RepoRef("a/b", "x"),
        RepoRef("a b", "x"),
        RepoRef("", "x"),
        RepoRef("javascript:", "x"),
        RepoRef("a", "."),
        RepoRef("a", ".."),
        RepoRef("a", "x?y"),
        RepoRef("a", "x#y"),
    ],
)
def test_unsafe_parts_are_refused(repo: RepoRef) -> None:
    assert not is_safe_repo(repo)
    with pytest.raises(ValueError, match="unsafe repository name"):
        repo_url(repo)
    with pytest.raises(ValueError, match="unsafe repository name"):
        pull_url(repo, 1)
    with pytest.raises(ValueError, match="unsafe repository name"):
        issue_url(repo, 1)


def test_numbers_below_one_are_refused() -> None:
    with pytest.raises(ValueError, match="invalid number"):
        pull_url(RepoRef("a", "b"), 0)
    with pytest.raises(ValueError, match="invalid number"):
        issue_url(RepoRef("a", "b"), -3)


def test_clean_title_strips_controls_and_bidi() -> None:
    right_to_left_override = chr(0x202E)
    assert clean_title(f"a{right_to_left_override}b\x00c\n d") == "abc d"


def test_clean_title_keeps_markup_as_text() -> None:
    assert clean_title("<script>x</script>") == "<script>x</script>"


@given(st.text(max_size=1000))
def test_clean_title_caps_length(raw: str) -> None:
    assert len(clean_title(raw)) <= MAX_TITLE


def test_unchecked_findings_counts_open_boxes_at_line_start() -> None:
    assert unchecked_findings("- [ ] a\n- [x] b\n  - [ ] c\n- [ ] d") == 2


def test_iso_is_utc_z() -> None:
    assert iso(datetime(2026, 10, 19, 6, 0, tzinfo=UTC)) == "2026-10-19T06:00:00Z"
    plus_two = datetime(2026, 10, 19, 8, 0, tzinfo=timezone(timedelta(hours=2)))
    assert iso(plus_two) == "2026-10-19T06:00:00Z"
    assert iso(None) is None
