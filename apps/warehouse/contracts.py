"""Domain validation for warehouse configuration documents."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError


def validate_warehouse_settings_payload(payload: Any) -> dict[str, Any]:
    """Validate and return a normalized warehouse settings document.

    Warning thresholds are kept in ascending order so consumers can apply the
    first matching threshold deterministically.  A list is used deliberately:
    it leaves room for several named UI bands without changing the document
    boundary.
    """
    if not isinstance(payload, dict):
        raise ValidationError("Настройки склада должны быть JSON-объектом.")
    required = {"default_quantity_precision", "expiry_warning_days"}
    missing = required - payload.keys()
    if missing:
        raise ValidationError(f"Отсутствуют обязательные поля: {', '.join(sorted(missing))}.")
    precision = payload["default_quantity_precision"]
    if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 6:
        raise ValidationError("default_quantity_precision должен быть целым числом от 0 до 6.")
    thresholds = payload["expiry_warning_days"]
    if not isinstance(thresholds, list) or not thresholds:
        raise ValidationError("expiry_warning_days должен быть непустым списком.")
    if any(isinstance(day, bool) or not isinstance(day, int) or day < 0 for day in thresholds):
        raise ValidationError("Пороги истечения должны быть неотрицательными целыми числами.")
    if thresholds != sorted(thresholds) or len(thresholds) != len(set(thresholds)):
        raise ValidationError("Пороги истечения должны быть уникальными и упорядоченными по возрастанию.")
    if set(payload) != required:
        extra = sorted(set(payload) - required)
        raise ValidationError(f"Неизвестные поля настроек склада: {', '.join(extra)}.")
    return {"default_quantity_precision": precision, "expiry_warning_days": list(thresholds)}
