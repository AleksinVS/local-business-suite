from __future__ import annotations

from collections.abc import Mapping, Sequence

from .deidentification import redact_text
from .security import scan_for_secrets

SENSITIVE_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "private_key",
    "raw_query",
    "query",
    "raw_text",
    "extracted_text",
    "full_text",
}


def safe_review_text(value: object, *, max_length: int = 500) -> str:
    text = str(value or "")
    if not text:
        return ""
    if scan_for_secrets(text).blocked:
        return "[blocked: secret-like value]"
    result = redact_text(text, replacement_template="[{entity_type}]")
    if result.blocked:
        return "[blocked: secret-like value]"
    safe_text = result.safe_text
    if len(safe_text) > max_length:
        return safe_text[: max_length - 1] + "…"
    return safe_text


def safe_review_metadata(value: object, *, depth: int = 0):
    if depth > 5:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return safe_review_text(value)
    if isinstance(value, Mapping):
        output = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                output[key_text] = "[redacted]"
                continue
            output[key_text] = safe_review_metadata(item, depth=depth + 1)
        return output
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [safe_review_metadata(item, depth=depth + 1) for item in list(value)[:50]]
    return safe_review_text(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    if normalized in SENSITIVE_KEYS:
        return True
    return any(token in normalized for token in ("secret", "password", "token", "private_key", "raw_query", "raw_text"))
