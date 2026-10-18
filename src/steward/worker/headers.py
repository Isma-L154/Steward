from collections.abc import Mapping
from types import MappingProxyType

API_HEADERS: Mapping[str, str] = MappingProxyType(
    {
        # No HTML is ever served, so nothing may load or frame a response.
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }
)
