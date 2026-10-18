from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from steward.config import MissingConfig, load_config

NAMES = ("APP_ID", "PRIVATE_KEY", "WEBHOOK_SECRET", "OWNER_EMAIL")


def _env(rsa_pem: str, **overrides: str) -> SimpleNamespace:
    values = {
        "APP_ID": "123",
        "PRIVATE_KEY": rsa_pem,
        "WEBHOOK_SECRET": "s3cret",
        "OWNER_EMAIL": "ismaleonsaenz@gmail.com",
    } | overrides
    return SimpleNamespace(**values)


def test_load_config_reads_all_three(rsa_key: RSAPrivateKey, rsa_pem: str) -> None:
    config = load_config(_env(rsa_pem))
    assert config.app_id == "123"
    assert config.webhook_secret == b"s3cret"
    assert config.owner_email == "ismaleonsaenz@gmail.com"
    assert config.private_key_pkcs8 == rsa_key.private_bytes(
        Encoding.DER, PrivateFormat.PKCS8, NoEncryption()
    )


@pytest.mark.parametrize("missing", NAMES)
def test_blank_variable_is_named(rsa_pem: str, missing: str) -> None:
    with pytest.raises(MissingConfig, match=missing):
        load_config(_env(rsa_pem, **{missing: "  "}))


@pytest.mark.parametrize("missing", NAMES)
def test_absent_variable_is_named(rsa_pem: str, missing: str) -> None:
    env = _env(rsa_pem)
    delattr(env, missing)
    with pytest.raises(MissingConfig, match=missing):
        load_config(env)


def test_unparseable_private_key_is_missing_config(rsa_pem: str) -> None:
    with pytest.raises(MissingConfig, match="PRIVATE_KEY"):
        load_config(_env(rsa_pem, PRIVATE_KEY="not a key"))


def test_non_rsa_private_key_is_missing_config(rsa_pem: str) -> None:
    ec_pem = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        .decode()
    )
    with pytest.raises(MissingConfig, match="PRIVATE_KEY"):
        load_config(_env(rsa_pem, PRIVATE_KEY=ec_pem))
