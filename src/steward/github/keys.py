import base64
import binascii
import re

# WebCrypto imports RSA private keys only as PKCS#8; GitHub hands out PKCS#1 ("RSA PRIVATE
# KEY"). PKCS#8 is the PKCS#1 key inside a fixed envelope, so the conversion needs no library.
_PEM = re.compile(r"-----BEGIN (RSA PRIVATE KEY|PRIVATE KEY)-----(.*?)-----END \1-----", re.DOTALL)
_VERSION_0 = bytes.fromhex("020100")
_RSA_ALGORITHM = bytes.fromhex("300d06092a864886f70d0101010500")


class InvalidKey(Exception):
    """The text is not an RSA private key in PKCS#1 or PKCS#8 PEM form."""


def _der_length(length: int) -> bytes:
    if length < 0x80:  # noqa: PLR2004 - DER short form
        return bytes([length])
    encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(encoded)]) + encoded


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _der_length(len(value)) + value


def pkcs8_der(pem: str) -> bytes:
    match = _PEM.search(pem.replace("\r", ""))
    if match is None:
        raise InvalidKey
    try:
        der = base64.b64decode("".join(match.group(2).split()), validate=True)
    except binascii.Error as error:
        raise InvalidKey from error
    if not der:
        raise InvalidKey
    if match.group(1) == "PRIVATE KEY":
        # The envelope starts with version 0 and the RSA algorithm, right after its own header.
        if _VERSION_0 + _RSA_ALGORITHM not in der[:32]:
            raise InvalidKey
        return der
    return _tlv(0x30, _VERSION_0 + _RSA_ALGORITHM + _tlv(0x04, der))
