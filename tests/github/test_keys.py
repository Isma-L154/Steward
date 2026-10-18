import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_der_private_key,
)

from steward.github.keys import InvalidKey, pkcs8_der


def _pem(key: RSAPrivateKey, fmt: PrivateFormat) -> str:
    return key.private_bytes(Encoding.PEM, fmt, NoEncryption()).decode()


def test_pkcs1_pem_is_wrapped_into_the_same_pkcs8_der(rsa_key: RSAPrivateKey) -> None:
    expected = rsa_key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    assert pkcs8_der(_pem(rsa_key, PrivateFormat.TraditionalOpenSSL)) == expected


def test_pkcs8_pem_is_decoded_as_is(rsa_key: RSAPrivateKey) -> None:
    expected = rsa_key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    assert pkcs8_der(_pem(rsa_key, PrivateFormat.PKCS8)) == expected


def test_wrapped_key_loads_back_as_the_same_key(rsa_key: RSAPrivateKey) -> None:
    der = pkcs8_der(_pem(rsa_key, PrivateFormat.TraditionalOpenSSL))
    loaded = load_der_private_key(der, password=None)
    assert isinstance(loaded, RSAPrivateKey)
    assert loaded.private_numbers() == rsa_key.private_numbers()


def test_surrounding_whitespace_and_crlf_are_tolerated(rsa_key: RSAPrivateKey) -> None:
    pem = "\n  " + _pem(rsa_key, PrivateFormat.TraditionalOpenSSL).replace("\n", "\r\n") + "  \n"
    expected = rsa_key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    assert pkcs8_der(pem) == expected


@pytest.mark.parametrize(
    "pem",
    [
        "not a key",
        "-----BEGIN EC PRIVATE KEY-----\nAAAA\n-----END EC PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----\n!!!not base64!!!\n-----END RSA PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----\n\n-----END RSA PRIVATE KEY-----",
    ],
)
def test_anything_else_is_invalid(pem: str) -> None:
    with pytest.raises(InvalidKey):
        pkcs8_der(pem)


def test_pkcs8_key_that_is_not_rsa_is_invalid() -> None:
    from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415

    pem = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        .decode()
    )
    with pytest.raises(InvalidKey):
        pkcs8_der(pem)
