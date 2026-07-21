"""Валидаторы core-workflow контрактов, не принадлежащих доменным приложениям.

Сюда вынесены три валидатора, которые не относятся к конкретному бизнес-домену
(memory/ai/analytics/workorders), а описывают общие для проекта артефакты:

* ``validate_integration_registry_payload`` — структура общего реестра внешних
  систем (``contracts/integrations/registry.json``). По правилу 3 AGENTS.md это
  общий список интеграций уровня SDK/транспорта, а не доменное правило: сюда не
  входит маппинг внешних данных в модели конкретного приложения.
* ``validate_task_brief_payload`` / ``validate_change_plan_payload`` — артефакты
  агентного workflow (task brief и change plan), которыми оперирует core-команда
  ``generate_change_plan``. Они относятся к процессу разработки, а не к бизнес-домену.

Модуль импортирует только универсальный примитив ``_ensure_non_empty_mapping`` из
``apps.core.json_utils`` (без обратной зависимости).
"""
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
