from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.hashes import SHA256


class CryptographySigner:
    """RS256 with the cryptography package: the reference the Worker's WebCrypto must match."""

    def __init__(self, key: RSAPrivateKey) -> None:
        self._key = key

    async def sign(self, data: bytes) -> bytes:
        return self._key.sign(data, PKCS1v15(), SHA256())
