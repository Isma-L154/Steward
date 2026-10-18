from typing import Any

from js import Object, Uint8Array, crypto
from pyodide.ffi import to_js


class WebCryptoSigner:
    """Signer over the runtime's native WebCrypto: RSA in WebAssembly costs too much CPU time."""

    def __init__(self, pkcs8: bytes) -> None:
        self._pkcs8 = pkcs8
        self._key: Any = None

    async def sign(self, data: bytes) -> bytes:
        algorithm = to_js(
            {"name": "RSASSA-PKCS1-v1_5", "hash": "SHA-256"}, dict_converter=Object.fromEntries
        )
        if self._key is None:
            self._key = await crypto.subtle.importKey(
                "pkcs8", to_js(self._pkcs8), algorithm, False, to_js(["sign"])
            )
        signature = await crypto.subtle.sign(algorithm, self._key, to_js(data))
        return bytes(Uint8Array.new(signature).to_py())
