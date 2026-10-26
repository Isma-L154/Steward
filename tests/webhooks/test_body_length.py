import pytest
from hypothesis import given
from hypothesis import strategies as st

from steward.webhooks.events import MAX_BODY_BYTES, is_acceptable_length


@pytest.mark.parametrize("declared", ["0", "512", str(MAX_BODY_BYTES)])
def test_a_small_declared_length_is_accepted(declared: str) -> None:
    assert is_acceptable_length(declared)


@pytest.mark.parametrize(
    "declared",
    [
        None,
        "",
        str(MAX_BODY_BYTES + 1),
        "-1",
        "+1",
        " 12",
        "1e3",
        # Header values reach Python as Latin-1: str.isdigit() accepts these, int() does not.
        "\N{SUPERSCRIPT ONE}",
        # Digits outside ASCII are no HTTP length, even where int() would read them.
        "\N{ARABIC-INDIC DIGIT THREE}",
        # Past Python's limit on converting digit strings to int.
        "9" * 5000,
    ],
)
def test_anything_else_is_refused(declared: str | None) -> None:
    assert not is_acceptable_length(declared)


@given(st.text())
def test_any_text_is_answered_and_only_ascii_digits_within_the_limit_pass(declared: str) -> None:
    if is_acceptable_length(declared):
        assert declared.isascii()
        assert declared.isdigit()
        assert int(declared) <= MAX_BODY_BYTES


@given(st.integers(min_value=0, max_value=10 * MAX_BODY_BYTES))
def test_a_length_passes_exactly_when_it_is_within_the_limit(length: int) -> None:
    assert is_acceptable_length(str(length)) == (length <= MAX_BODY_BYTES)
