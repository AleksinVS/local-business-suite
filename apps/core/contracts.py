"""Валидаторы общих контрактных структур проекта.

Сюда вынесены три валидатора, которые не относятся к конкретному бизнес-домену
(memory/ai/analytics/workorders), а описывают общие для проекта артефакты:

* ``validate_integration_registry_payload`` — структура общего реестра внешних
  систем (``contracts/integrations/registry.json``). По правилу 3 AGENTS.md это
  общий список интеграций уровня SDK/транспорта, а не доменное правило: сюда не
  входит маппинг внешних данных в модели конкретного приложения.
* ``validate_task_brief_payload`` / ``validate_change_plan_payload`` — артефакты
  агентного workflow (task brief и change plan), которыми оперирует core-команда
  ``generate_change_plan``. Они относятся к процессу разработки, а не к бизнес-домену.
* ``validate_status_colors_payload`` — общий формат палитры статусов. Набор
  допустимых статусов по-прежнему задаёт вызывающее доменное приложение.

Модуль импортирует только универсальный примитив ``_ensure_non_empty_mapping`` из
``apps.core.json_utils`` (без обратной зависимости).
"""
import re

from django.core.exceptions import ValidationError

from apps.core.json_utils import _ensure_non_empty_mapping


REQUIRED_INTEGRATION_KEYS = {
    "code",
    "name",
    "owner",
    "transport",
    "mode",
    "direction",
    "status",
    "source_of_truth",
    "payloads",
}

REQUIRED_TASK_BRIEF_KEYS = {
    "id",
    "title",
    "status",
    "requested_by",
    "target_modules",
    "objective",
    "constraints",
    "deliverables",
    "acceptance_checks",
}

REQUIRED_CHANGE_PLAN_KEYS = {
    "brief_id",
    "title",
    "status",
    "summary",
    "assumptions",
    "affected_files",
    "steps",
    "verification",
    "risks",
}

HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


def validate_integration_registry_payload(payload):
    if not isinstance(payload, list):
        raise ValidationError("Реестр интеграций должен быть JSON-массивом.")
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"Элемент интеграции #{index} должен быть JSON-объектом.")
        missing = REQUIRED_INTEGRATION_KEYS - set(item.keys())
        if missing:
            raise ValidationError(
                f"Интеграция '{item.get('code', index)}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing))}."
            )
        if not isinstance(item["payloads"], list):
            raise ValidationError(f"Интеграция '{item['code']}' должна содержать список payloads.")


def validate_task_brief_payload(payload):
    _ensure_non_empty_mapping(payload, "Task brief")
    missing = REQUIRED_TASK_BRIEF_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Task brief не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for key in ("target_modules", "constraints", "deliverables", "acceptance_checks"):
        if not isinstance(payload.get(key), list):
            raise ValidationError(f"Поле '{key}' в task brief должно быть списком.")


def validate_change_plan_payload(payload):
    _ensure_non_empty_mapping(payload, "Change plan")
    missing = REQUIRED_CHANGE_PLAN_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Change plan не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for key in ("assumptions", "affected_files", "steps", "verification", "risks"):
        if not isinstance(payload.get(key), list):
            raise ValidationError(f"Поле '{key}' в change plan должно быть списком.")


def validate_status_colors_payload(payload, *, subject, known_statuses):
    """Проверить общую структуру палитры и точный доменный набор статусов."""

    _ensure_non_empty_mapping(payload, f"Конфигурация цветов статусов {subject}")
    statuses = payload.get("statuses")
    if not isinstance(statuses, dict) or not statuses:
        raise ValidationError("Поле statuses должно быть непустым JSON-объектом.")

    known_statuses = set(known_statuses or ())
    if known_statuses:
        missing = known_statuses - set(statuses)
        if missing:
            raise ValidationError(
                "Для некоторых статусов не заданы цвета: "
                + ", ".join(sorted(missing))
                + "."
            )
        extra = set(statuses) - known_statuses
        if extra:
            raise ValidationError(
                "В цветах описаны неизвестные статусы: "
                + ", ".join(sorted(extra))
                + "."
            )

    for status, config in statuses.items():
        if not isinstance(status, str) or not status:
            raise ValidationError("Код статуса должен быть непустой строкой.")
        if not isinstance(config, dict):
            raise ValidationError(f"Настройка статуса '{status}' должна быть JSON-объектом.")
        missing_keys = {"label", "color", "background"} - set(config)
        if missing_keys:
            raise ValidationError(
                f"Настройка статуса '{status}' не содержит поля: "
                + ", ".join(sorted(missing_keys))
                + "."
            )
        if not isinstance(config.get("label"), str) or not config["label"].strip():
            raise ValidationError(
                f"Поле label у статуса '{status}' должно быть непустой строкой."
            )
        for key in ("color", "background"):
            value = config.get(key)
            if not isinstance(value, str) or not HEX_COLOR_PATTERN.fullmatch(value):
                raise ValidationError(
                    f"Поле {key} у статуса '{status}' должно быть цветом HEX вида #RRGGBB."
                )
