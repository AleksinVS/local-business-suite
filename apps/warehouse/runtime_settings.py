"""Read-only compatibility adapter for the warehouse settings document."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from typing import Any

from django.conf import settings

from .contracts import validate_warehouse_settings_payload


WAREHOUSE_SETTINGS_DOCUMENT_ID = "warehouse.settings"


def get_warehouse_runtime_settings(request=None) -> dict[str, Any]:
    """Return effective warehouse settings without writing or caching globally.

    The repository branch is intentionally discovered lazily.  This lets the
    warehouse ship before the settings-center document store and gives the
    parallel migration a stable seam to replace later.
    """
    repository_value = _read_from_repository(request)
    if repository_value is not None:
        return copy.deepcopy(validate_warehouse_settings_payload(repository_value))
    for path in _runtime_paths():
        value = _read_json(path)
        if value is not None:
            return validate_warehouse_settings_payload(value)
    value = _read_json(_git_default_path())
    if value is None:
        raise RuntimeError("Не найден Git-дефолт настроек склада.")
    return validate_warehouse_settings_payload(value)


def _read_from_repository(request):
    try:
        module = importlib.import_module("apps.settings_center.document_repository")
    except (ImportError, ModuleNotFoundError):
        return None
    getter = getattr(module, "get_document", None)
    if not callable(getter):
        return None
    try:
        value = getter(WAREHOUSE_SETTINGS_DOCUMENT_ID, request=request)
    except LookupError:
        # The target repository can land before the warehouse document is
        # registered in it.  During that short compatibility window the
        # existing file-backed contract remains the source of truth.
        return None
    if value is None:
        return None
    if isinstance(value, dict) and "payload" in value and set(value) <= {"payload", "document_id", "revision", "schema_version", "content_hash"}:
        return value["payload"]
    payload = getattr(value, "payload", None)
    return payload if payload is not None else value


def _runtime_paths() -> tuple[Path, ...]:
    explicit = getattr(settings, "WAREHOUSE_RUNTIME_SETTINGS_FILE", None)
    paths = [Path(explicit)] if explicit else []
    runtime_dir = getattr(settings, "RUNTIME_CONTRACTS_DIR", None)
    if runtime_dir:
        paths.append(Path(runtime_dir) / "warehouse" / "settings.json")
    data_dir = getattr(settings, "DATA_DIR", None)
    if data_dir:
        paths.append(Path(data_dir) / "contracts" / "warehouse" / "settings.json")
    return tuple(dict.fromkeys(paths))


def _git_default_path() -> Path:
    return Path(settings.BASE_DIR) / "contracts" / "warehouse" / "settings.json"


def _read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
