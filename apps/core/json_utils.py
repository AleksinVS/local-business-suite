"""Универсальные JSON-примитивы уровня ядра (apps.core).

Здесь остаются только доменно-нейтральные утилиты, которые используются широко и
не знают ни о каком бизнес-домене:

* сериализация/чтение/атомарная запись JSON (``pretty_json``, ``load_json_file``,
  ``atomic_write_json``);
* общие внутренние проверки формы данных (``_ensure_*``), переиспользуемые
  валидаторами нескольких приложений.

Доменные валидаторы контрактов (memory/ai/analytics/workorders и core-workflow)
вынесены в модули ``contracts.py`` соответствующих приложений — по правилам 3 и 5
AGENTS.md ядро не должно знать доменные правила. Эти модули импортируют примитивы
отсюда; обратной зависимости нет.

ВНИМАНИЕ: ``config/settings.py`` импортирует ``load_json_file`` очень рано (до
готовности реестра приложений). Поэтому в этот модуль НЕЛЬЗЯ добавлять top-level
re-export вида ``from apps.<app>.contracts import ...`` — это затянет загрузку
``apps.*`` во время импорта settings и уронит старт (AppRegistryNotReady).
"""
import json
from pathlib import Path

from django.core.exceptions import ValidationError


def pretty_json(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def load_json_file(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_write_json(path, payload):
    """
    Writes a JSON payload to a file atomically using a temporary file.
    """
    import os
    import tempfile

    data = pretty_json(payload)
    path = Path(path)

    # Create temp file in the same directory to ensure os.replace works across devices
    fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(data)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def _ensure_non_empty_mapping(payload, label):
    if not isinstance(payload, dict) or not payload:
        raise ValidationError(f"{label} должна быть непустым JSON-объектом.")


def _ensure_list_of_strings(value, label):
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValidationError(f"{label} должен быть непустым списком строк.")


def _ensure_contract_list(payload, label, required_keys):
    if not isinstance(payload, list):
        raise ValidationError(f"{label} должен быть JSON-массивом.")
    if not payload:
        raise ValidationError(f"{label} должен содержать хотя бы один элемент.")
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"{label} #{index} должен быть JSON-объектом.")
        missing = required_keys - set(item.keys())
        if missing:
            raise ValidationError(
                f"{label} '{item.get('code', index)}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing))}."
            )
        for key in ("code", "title", "owner"):
            if key in required_keys and (not isinstance(item.get(key), str) or not item.get(key)):
                raise ValidationError(f"Поле {key} у {label} '{item.get('code', index)}' должно быть непустой строкой.")


def _ensure_unique_code(item, codes, label):
    code = item.get("code")
    if not isinstance(code, str) or not code:
        raise ValidationError(f"{label} содержит пустой code.")
    if code in codes:
        raise ValidationError(f"{label} '{code}' объявлен повторно.")
    codes.add(code)
    return code


def _ensure_positive_int(value, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValidationError(f"Поле {label} должно быть положительным числом.")


def _ensure_number(value, label: str) -> None:
    if not isinstance(value, (int, float)):
        raise ValidationError(f"Поле {label} должно быть числом.")
