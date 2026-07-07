"""Единый слой чтения рабочих копий бизнес-контрактов (ADR-0031).

Модуль устраняет межпроцессную несогласованность: вместо того чтобы держать
разобранные контракты в константах ``settings.*`` (обновляются только в одном
воркере после записи), процессы читают рабочую копию из ``data/contracts/`` по
требованию и кэшируют разобранный payload по ключу метаданных файла.

Методическая заметка (для обучающего контура проекта): ключ инвалидации кэша —
кортеж ``(st_mtime_ns, st_size, st_ino)``, а не голый ``mtime``. Атомарная запись
через ``os.replace`` меняет inode файла, поэтому inode в ключе делает
инвалидацию надёжной даже на файловых системах с грубым разрешением ``mtime``.
Цена одного обращения — один системный вызов ``stat``, что несопоставимо дешевле
повторного разбора и валидации JSON.
"""
from __future__ import annotations

import hashlib
import logging
import os
from copy import deepcopy

from django.conf import settings

from apps.core.json_utils import (
    load_json_file,
    pretty_json,
)
from apps.workorders.contracts import (
    validate_role_rules_payload,
    validate_workflow_rules_payload,
    validate_workorder_status_colors_payload,
)

logger = logging.getLogger(__name__)


class ContractStoreError(RuntimeError):
    """Контракт нельзя прочитать, и валидного снимка в процессе ещё нет."""


# Реестр контрактов, которые обслуживает store: имя -> путь и валидатор.
# Путь берётся из ``settings.LOCAL_BUSINESS_*_FILE`` (уважает env-override,
# который settings.py уже применил к этим константам).
#
# На пути чтения каждый контракт валидируется автономно (без кросс-проверки
# против workflow_rules): каскадная зависимость чтения одного контракта от
# другого давала бы ложную деградацию role_rules при проблемах workflow-файла.
# Кросс-валидация пар контрактов выполняется на пути записи
# (``apps.settings_center.contract_services.VALIDATORS``), при старте процесса
# (``config/settings.py``) и командой ``validate_architecture_contracts``.
_CONTRACTS = {
    "role_rules": {
        "path_setting": "LOCAL_BUSINESS_ROLE_RULES_FILE",
        "validator": validate_role_rules_payload,
    },
    "workflow_rules": {
        "path_setting": "LOCAL_BUSINESS_WORKFLOW_RULES_FILE",
        "validator": validate_workflow_rules_payload,
    },
    "workorder_status_colors": {
        "path_setting": "LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE",
        "validator": validate_workorder_status_colors_payload,
    },
}

# Процессный кэш: имя -> {"key": кортеж метаданных, "payload": разобранный dict}.
# ``payload`` считается приватным и наружу отдаётся только глубокой копией.
_cache: dict[str, dict] = {}

# Видимый сигнал деградации: имя -> текст последней ошибки перечтения.
_degraded: dict[str, str] = {}


def _stat_key(path):
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _load_current(name: str):
    """Возвращает актуальный разобранный payload (приватный, не для мутации)."""
    try:
        cfg = _CONTRACTS[name]
    except KeyError as exc:
        raise ContractStoreError(f"Неизвестный контракт: '{name}'.") from exc

    path = getattr(settings, cfg["path_setting"])
    try:
        key = _stat_key(path)
    except OSError as exc:
        return _handle_failure(name, exc)

    entry = _cache.get(name)
    if entry is not None and entry["key"] == key:
        return entry["payload"]

    try:
        payload = load_json_file(path)
        # Валидируем копию: некоторые валидаторы нормализуют payload на месте
        # (setdefault обратной совместимости). Кэшируем именно разобранный файл,
        # чтобы кэш не мутировался и хеш совпадал с фактическим содержимым файла.
        cfg["validator"](deepcopy(payload))
    except Exception as exc:  # noqa: BLE001 — сюда попадают JSON/валидация/IO
        return _handle_failure(name, exc)

    _cache[name] = {"key": key, "payload": payload}
    _degraded.pop(name, None)
    return payload


def _handle_failure(name: str, exc: Exception):
    entry = _cache.get(name)
    if entry is None:
        # Первое чтение после старта процесса — поднимаем ошибку наверх (fail-fast).
        raise ContractStoreError(
            f"Не удалось загрузить контракт '{name}' при первом чтении: {exc}"
        ) from exc
    # Валидный снимок уже был: отдаём последний валидный payload, но фиксируем
    # видимый сигнал деградации и пишем ERROR, чтобы тихий откат не маскировал сбой.
    _degraded[name] = str(exc)
    logger.error(
        "Контракт '%s' не удалось перечитать, используется последний валидный "
        "снимок: %s",
        name,
        exc,
    )
    return entry["payload"]


def get_contract(name: str, request=None):
    """Возвращает неизменяемый (для вызывающего) снимок рабочего контракта.

    Наружу всегда отдаётся глубокая копия кэшированного payload, поэтому мутация
    результата вызывающим кодом не портит процессный кэш.

    Если передан ``request``, используется снимок на время HTTP-запроса: контракт
    читается один раз за запрос и переиспользуется, чтобы запрос не увидел две
    версии правил (важно для авторизационных решений). В местах, где ``request``
    недоступен, вызывается ``get_contract(name)`` — согласованность в пределах
    запроса в типичном случае обеспечивает кэш по ключу метаданных.
    """
    if request is not None:
        snapshots = getattr(request, "_contract_snapshots", None)
        if snapshots is None:
            snapshots = {}
            try:
                request._contract_snapshots = snapshots
            except (AttributeError, TypeError):
                snapshots = None
        if snapshots is not None:
            if name not in snapshots:
                snapshots[name] = _load_current(name)
            return deepcopy(snapshots[name])

    return deepcopy(_load_current(name))


def normalized_hash(payload) -> str:
    """sha256 нормализованного (канонического) представления payload.

    Нормализация (``pretty_json`` с ``sort_keys``) делает хеш устойчивым к
    различиям в форматировании и порядке ключей.
    """
    return hashlib.sha256(pretty_json(payload).encode("utf-8")).hexdigest()


def current_contract_hash(name: str) -> str:
    """Хеш актуальной версии контракта для оптимистической проверки записи."""
    return normalized_hash(get_contract(name))


def registered_contracts() -> tuple:
    """Имена контрактов, которые обслуживает store (для активных health-проверок)."""
    return tuple(_CONTRACTS)


def get_degradation_state() -> dict:
    """Видимое состояние деградации store для /health/ и Settings Center."""
    contracts = dict(_degraded)
    return {"degraded": bool(contracts), "contracts": contracts}


def _reset_for_tests() -> None:
    """Сбрасывает процессный кэш и сигнал деградации (только для тестов)."""
    _cache.clear()
    _degraded.clear()
