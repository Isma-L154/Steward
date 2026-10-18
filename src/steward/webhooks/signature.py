import hashlib
import hmac

_PREFIX = "sha256="


def is_valid_signature(secret: bytes, body: bytes, header: str | None) -> bool:
    """Checks GitHub's X-Hub-Signature-256 header against the raw body."""
    if not header or not header.startswith(_PREFIX):
        return False
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix(_PREFIX))
