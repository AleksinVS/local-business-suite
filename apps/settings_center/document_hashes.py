"""Каноническое представление и хеши документов настроек.

Хеш используется одновременно для оптимистической конкуренции, аудита и ETag.
Поэтому он считается по полному JSON без маскирования и имеет один формат:
64 шестнадцатеричных символа SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class InvalidDocumentPayload(ValueError):
    """Payload нельзя представить допустимым каноническим JSON."""


def _validate_json_value(value: Any, *, seen: set[int]) -> None:
    """Запретить неявные преобразования Python-типов в другой JSON-смысл."""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise InvalidDocumentPayload("NaN и Infinity запрещены в документе настроек.")
    if isinstance(value, list):
        identity = id(value)
        if identity in seen:
            raise InvalidDocumentPayload("Циклические JSON-структуры запрещены.")
        seen.add(identity)
        try:
            for item in value:
                _validate_json_value(item, seen=seen)
        finally:
            seen.remove(identity)
        return
    if isinstance(value, dict):
        identity = id(value)
        if identity in seen:
            raise InvalidDocumentPayload("Циклические JSON-структуры запрещены.")
        seen.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise InvalidDocumentPayload("Ключи JSON-объекта должны быть строками.")
                _validate_json_value(item, seen=seen)
        finally:
            seen.remove(identity)
        return
    raise InvalidDocumentPayload(
        f"Тип {type(value).__name__} не является допустимым JSON-значением."
    )


def canonical_json(value: Any) -> str:
    """Вернуть стабильный JSON и отклонить не-JSON значения и NaN/Infinity."""

    _validate_json_value(value, seen=set())
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidDocumentPayload(
            "Документ должен содержать только допустимые JSON-значения."
        ) from exc


def document_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def is_document_hash(value: str) -> bool:
    value = str(value or "")
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
