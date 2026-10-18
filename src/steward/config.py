from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


class MissingConfig(Exception):
    """A required variable is absent, blank or unusable; the message is its name."""


@dataclass(frozen=True)
class Config:
    app_id: str
    private_key: RSAPrivateKey
    webhook_secret: bytes


def _required(env: Any, name: str) -> str:
    value = getattr(env, name, None)
    if value is None or not str(value).strip():
        raise MissingConfig(name)
    return str(value).strip()


def _private_key(pem: str) -> RSAPrivateKey:
    # Imported here, not at module level: cryptography reads entropy on import, which the
    # Workers runtime forbids while it loads the Worker's top-level modules.
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey  # noqa: PLC0415
    from cryptography.hazmat.primitives.serialization import (  # noqa: PLC0415
        load_pem_private_key,
    )

    try:
        key = load_pem_private_key(pem.encode(), password=None)
    except ValueError as error:
        raise MissingConfig("PRIVATE_KEY") from error
    if not isinstance(key, RSAPrivateKey):
        raise MissingConfig("PRIVATE_KEY")
    return key


def load_config(env: Any) -> Config:
    return Config(
        app_id=_required(env, "APP_ID"),
        private_key=_private_key(_required(env, "PRIVATE_KEY")),
        webhook_secret=_required(env, "WEBHOOK_SECRET").encode(),
    )
