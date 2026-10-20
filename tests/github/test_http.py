import json

from hypothesis import given
from hypothesis import strategies as st

from steward.github.http import MAX_DETAIL, GitHubError, answer_detail

_TOKEN_CHARS = st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_TOKENS = st.one_of(
    st.builds(
        "".join,
        st.tuples(
            st.sampled_from(["ghs_", "ghp_", "gho_", "ghu_", "ghr_", "github_pat_"]),
            _TOKEN_CHARS.filter(bool),
        ),
    ),
    st.builds(
        lambda header, claims, signature: f"eyJ{header}.{claims}.{signature}",
        _TOKEN_CHARS,
        _TOKEN_CHARS,
        _TOKEN_CHARS,
    ),
)


def _body(**answer: object) -> str:
    return json.dumps(answer)


def test_message_and_documentation_url_are_kept() -> None:
    body = _body(message="Not Found", documentation_url="https://docs.github.com/rest/repos")
    assert answer_detail(body) == "Not Found (https://docs.github.com/rest/repos)"


def test_documentation_url_outside_github_docs_is_dropped() -> None:
    assert answer_detail(_body(message="Nope", documentation_url="https://evil.test/x")) == "Nope"


def test_first_graphql_error_message_is_used() -> None:
    body = _body(data=None, errors=[{"message": "Could not resolve"}, {"message": "second"}])
    assert answer_detail(body) == "Could not resolve"


def test_answer_without_a_message_has_no_detail() -> None:
    assert answer_detail("") is None
    assert answer_detail("<html>bad gateway</html>") is None
    assert answer_detail("[1, 2]") is None
    assert answer_detail(_body(message=3)) is None
    assert answer_detail(_body(errors=[{"code": "invalid"}])) is None


def test_control_characters_and_whitespace_are_flattened() -> None:
    assert answer_detail(_body(message="a\nb\r\n\x1b[31mc\u2028d\x00")) == "a b [31mc d"


def test_detail_is_bounded() -> None:
    detail = answer_detail(_body(message="x" * 10_000))
    assert detail is not None
    assert len(detail) == MAX_DETAIL


@given(token=_TOKENS, before=st.text(max_size=50), after=st.text(max_size=50))
def test_a_token_never_reaches_the_detail(token: str, before: str, after: str) -> None:
    body = _body(
        message=f"{before} {token} {after}", documentation_url=f"https://docs.github.com/{token}"
    )
    detail = answer_detail(body) or ""
    assert token not in detail


def test_authorization_value_is_redacted() -> None:
    detail = answer_detail(_body(message="sent Authorization: Bearer abc.def-ghi and failed"))
    assert detail == "sent Authorization: [redacted] and failed"


def test_error_message_carries_the_detail() -> None:
    error = GitHubError(422, "/app/installations/1/access_tokens", "Missing permission")
    assert (
        str(error)
        == "GitHub answered 422 for /app/installations/1/access_tokens: Missing permission"
    )
    assert error.detail == "Missing permission"


def test_error_message_without_detail_is_unchanged() -> None:
    assert str(GitHubError(500, "/x")) == "GitHub answered 500 for /x"
