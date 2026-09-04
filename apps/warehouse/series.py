"""Canonical handling of inline warehouse series values.

The displayed value keeps the user's letter case, while ``series_key`` is a
stable comparison key.  This module deliberately owns no database queries so
it can also be embedded verbatim in historical data migrations.
"""

from __future__ import annotations

import re
import unicodedata

from django.core.exceptions import ValidationError


SERIES_MAX_LENGTH = 255
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_series_display(value: object) -> str:
    """Return NFC text with outer/repeated whitespace removed."""

    text = unicodedata.normalize("NFC", str(value or ""))
    text = _WHITESPACE_RE.sub(" ", text.strip())
    if len(text) > SERIES_MAX_LENGTH:
        raise ValidationError(
            {"series": f"Серия не должна быть длиннее {SERIES_MAX_LENGTH} символов."}
        )
    return text


def normalize_series_key(value: object) -> str:
    """Return the case-insensitive key for a displayed series value."""

    key = normalize_series_display(value).casefold()
    if len(key) > SERIES_MAX_LENGTH:
        raise ValidationError(
            {"series": "Нормализованное значение серии слишком длинное."}
        )
    return key


def normalize_series(value: object) -> tuple[str, str]:
    display = normalize_series_display(value)
    return display, normalize_series_key(display)
