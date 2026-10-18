import hashlib
import hmac

import pytest

from steward.webhooks.signature import is_valid_signature


def _sign(secret: bytes, body: bytes) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def test_valid_signature_accepted() -> None:
    body = b'{"zen":"hi"}'
    assert is_valid_signature(b"k", body, _sign(b"k", body))


def test_signature_for_other_body_rejected() -> None:
    assert not is_valid_signature(b"k", b'{"zen":"bye"}', _sign(b"k", b'{"zen":"hi"}'))


def test_signature_with_other_secret_rejected() -> None:
    assert not is_valid_signature(b"k", b"{}", _sign(b"other", b"{}"))


@pytest.mark.parametrize(
    "header", [None, "", "sha256=", "sha1=abc", "sha256=" + "0" * 64, "sha256=zz"]
)
def test_bad_signatures_rejected(header: str | None) -> None:
    assert not is_valid_signature(b"k", b"{}", header)
