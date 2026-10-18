from dataclasses import dataclass
from typing import Any

from steward.github.keys import InvalidKey, pkcs8_der


class MissingConfig(Exception):
    """A required variable is absent, blank or unusable; the message is its name."""


@dataclass(frozen=True)
class Config:
    app_id: str
    private_key_pkcs8: bytes
    webhook_secret: bytes


def _required(env: Any, name: str) -> str:
    value = getattr(env, name, None)
    if value is None or not str(value).strip():
        raise MissingConfig(name)
    return str(value).strip()


def load_config(env: Any) -> Config:
    try:
        private_key = pkcs8_der(_required(env, "PRIVATE_KEY"))
    except InvalidKey as error:
        raise MissingConfig("PRIVATE_KEY") from error
    return Config(
        app_id=_required(env, "APP_ID"),
        private_key_pkcs8=private_key,
        webhook_secret=_required(env, "WEBHOOK_SECRET").encode(),
    )
