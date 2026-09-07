import re
from collections.abc import Mapping, MutableMapping
from typing import Any

REDACTED = "[redacted]"
DROPPED = "[dropped]"
MAX_LOGGED_STRING_LENGTH = 512

SENSITIVE_KEY_FRAGMENTS: frozenset[str] = frozenset(
    {
        "access_key",
        "api_key",
        "apikey",
        "authorization",
        "broker_url",
        "credential",
        "database_url",
        "dsn",
        "jwt",
        "passwd",
        "password",
        "private_key",
        "redis_url",
        "refresh_token",
        "secret",
        "session_key",
        "signature",
        "token",
    }
)

CONTENT_KEY_FRAGMENTS: frozenset[str] = frozenset(
    {
        "answer",
        "blocks",
        "body",
        "chunk_text",
        "content",
        "document_text",
        "excerpt",
        "extracted_text",
        "file_bytes",
        "payload",
        "prompt",
        "query_text",
        "raw",
        "snippet",
        "text",
    }
)

_ALLOWED_URL_KEY_FRAGMENTS: frozenset[str] = frozenset({"endpoint_url", "issuer", "discovery_url"})

_CREDENTIALED_URL = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/@\s]+)@")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_LONG_SECRET = re.compile(r"\b(sk|xoxb|ghp|gho|AKIA)[-_A-Za-z0-9]{12,}\b")


def _matches(key: str, fragments: frozenset[str]) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in fragments)


def is_sensitive_key(key: str) -> bool:
    return _matches(key, SENSITIVE_KEY_FRAGMENTS)


def is_content_key(key: str) -> bool:
    return _matches(key, CONTENT_KEY_FRAGMENTS)


def scrub_text(value: str) -> str:
    scrubbed = _CREDENTIALED_URL.sub(r"\g<scheme>" + REDACTED + "@", value)
    scrubbed = _JWT.sub(REDACTED, scrubbed)
    scrubbed = _BEARER.sub(REDACTED, scrubbed)
    scrubbed = _LONG_SECRET.sub(REDACTED, scrubbed)
    if len(scrubbed) > MAX_LOGGED_STRING_LENGTH:
        return scrubbed[:MAX_LOGGED_STRING_LENGTH] + "…"
    return scrubbed


def _scrub_value(key: str, value: Any, *, depth: int) -> Any:
    if is_sensitive_key(key) and key.lower() not in _ALLOWED_URL_KEY_FRAGMENTS:
        return REDACTED
    if is_content_key(key):
        return DROPPED
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return DROPPED
    if depth <= 0:
        return value
    if isinstance(value, Mapping):
        return {
            str(inner_key): _scrub_value(str(inner_key), inner_value, depth=depth - 1)
            for inner_key, inner_value in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_scrub_value(key, item, depth=depth - 1) for item in value]
    return value


def redact_event(
    _logger: object,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    for key in list(event_dict.keys()):
        if key == "event":
            value = event_dict[key]
            if isinstance(value, str):
                event_dict[key] = scrub_text(value)
            continue
        event_dict[key] = _scrub_value(key, event_dict[key], depth=3)
    return event_dict


__all__ = [
    "CONTENT_KEY_FRAGMENTS",
    "DROPPED",
    "MAX_LOGGED_STRING_LENGTH",
    "REDACTED",
    "SENSITIVE_KEY_FRAGMENTS",
    "is_content_key",
    "is_sensitive_key",
    "redact_event",
    "scrub_text",
]
