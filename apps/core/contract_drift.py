"""Диагностика дрейфа между дефолтными контрактами (`contracts/`, git) и их
рабочими копиями (`data/contracts/`, редактируются через Settings Center и
AI-инструменты).

Проблема (ADR-0031, п.4 "Диагностика дрейфа default<->runtime"): `get_contract_path`
(``config/settings.py``) копирует дефолт в `data/contracts/` один раз, при первом
обращении к настройке. Дальнейшие изменения дефолта в git (разработчик обновил
контракт) никак не долетают до уже развернутой установки — рабочая копия просто
лежит и не «знает», что дефолт ушел вперед. До этого модуля такой дрейф не был
виден вообще ни для одного контракта: единственная существовавшая проверка,
``validate_ai_tools_drift`` (``apps/core/json_utils.py``), сверяет не файлы, а
Python-каталог инструментов (``apps.ai.tool_definitions.TOOLS``) с JSON-каталогом
``tools.json`` — это другой вид дрейфа (код vs JSON), не default-файл vs runtime-файл.

Модуль только ДИАГНОСТИРУЕТ дрейф — никогда не сливает и не перезаписывает файлы
(non-goal этого пакета: перенос обновленных дефолтов в рабочую копию остается
ручной операцией, см. `docs/guides/SETTINGS_CENTER_OPERATIONS.md`).

Для каждого контракта считаются три исхода:

- ``STATUS_IDENTICAL`` — рабочая копия по нормализованному хешу совпадает с
  дефолтом: дрейфа нет;
- ``STATUS_RUNTIME_CHANGED`` — набор ключей верхнего уровня не изменился, но
  содержимое отличается. Это ОЖИДАЕМОЕ состояние: администратор отредактировал
  рабочую копию через Settings Center (или дефолт поменял значение существующего
  ключа) — не ошибка и не повод для алармов;
- ``STATUS_CANDIDATE_FOR_MIGRATION`` — в дефолте появились ключи верхнего уровня,
  которых нет в рабочей копии. Это НЕ обязательно ошибка (рабочая копия валидна
  и работает по старой схеме), но самый ценный сигнал отчета: разработчик добавил
  новую опцию контракта в git, а уже развернутая установка ее не увидит, пока
  кто-то не перенесет значение в рабочую копию вручную.

Хеш и нормализация переиспользуют ``apps.core.contract_store.normalized_hash``
(sha256 от ``pretty_json`` с ``sort_keys=True``) — тот же хеш использует
оптимистическая проверка записи в ``contract_services.apply_contract_payload``,
поэтому отчет о дрейфе согласован с остальной системой, а не считает по-своему.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from apps.core.contract_store import normalized_hash
from apps.core.json_utils import load_json_file
from apps.settings_center.registry import get_registry


STATUS_IDENTICAL = "identical"
STATUS_RUNTIME_CHANGED = "runtime_changed"
STATUS_CANDIDATE_FOR_MIGRATION = "candidate_for_migration"
STATUS_ENV_OVERRIDE = "env_override"
STATUS_UNREADABLE = "unreadable"

# Статусы, которые считаются "дрейфом" для целей --fail-on-drift и summary.
# STATUS_ENV_OVERRIDE и STATUS_UNREADABLE намеренно не входят: это не дрейф
# содержимого, а невозможность его посчитать (переопределен путь / файл битый),
# они видны в отчете отдельной строкой, но не проваливают CI-флаг.
DRIFT_STATUSES = (STATUS_RUNTIME_CHANGED, STATUS_CANDIDATE_FOR_MIGRATION)

_STATUS_LABELS = {
    STATUS_IDENTICAL: "совпадает с дефолтом",
    STATUS_RUNTIME_CHANGED: "рабочая копия изменена (ожидаемо, не ошибка)",
    STATUS_CANDIDATE_FOR_MIGRATION: "кандидат на перенос из дефолта",
    STATUS_ENV_OVERRIDE: "путь переопределен переменной окружения, сравнение с дефолтом пропущено",
    STATUS_UNREADABLE: "не удалось прочитать/разобрать один из файлов",
}


@dataclass(frozen=True)
class ContractDriftEntry:
    """Результат сравнения одного контракта: дефолт vs рабочая копия."""

    name: str
    default_path: Path | None
    runtime_path: Path
    status: str
    missing_keys_in_runtime: tuple[str, ...] = ()
    extra_keys_in_runtime: tuple[str, ...] = ()
    detail: str = ""

    @property
    def label(self) -> str:
        return _STATUS_LABELS.get(self.status, self.status)

    @property
    def is_drift(self) -> bool:
        return self.status in DRIFT_STATUSES


def evaluate_contract_drift(name: str, default_path, runtime_path) -> ContractDriftEntry:
    """Сравнивает дефолт и рабочую копию одного контракта по явным путям.

    Не зависит от реестра настроек, поэтому вызывается напрямую в тестах на
    произвольных временных файлах и используется ``collect_contract_drift``
    для каждого зарегистрированного контракта.
    """
    default_path = Path(default_path)
    runtime_path = Path(runtime_path)

    missing = [str(path) for path in (default_path, runtime_path) if not path.exists()]
    if missing:
        return ContractDriftEntry(
            name=name,
            default_path=default_path,
            runtime_path=runtime_path,
            status=STATUS_UNREADABLE,
            detail="файл(ы) не найдены: " + ", ".join(missing),
        )

    try:
        default_payload = load_json_file(default_path)
        runtime_payload = load_json_file(runtime_path)
    except (OSError, ValueError) as exc:
        return ContractDriftEntry(
            name=name,
            default_path=default_path,
            runtime_path=runtime_path,
            status=STATUS_UNREADABLE,
            detail=f"не удалось разобрать JSON: {exc}",
        )

    if normalized_hash(default_payload) == normalized_hash(runtime_payload):
        return ContractDriftEntry(
            name=name,
            default_path=default_path,
            runtime_path=runtime_path,
            status=STATUS_IDENTICAL,
        )

    missing_keys: tuple[str, ...] = ()
    extra_keys: tuple[str, ...] = ()
    if isinstance(default_payload, dict) and isinstance(runtime_payload, dict):
        default_keys = set(default_payload)
        runtime_keys = set(runtime_payload)
        missing_keys = tuple(sorted(default_keys - runtime_keys))
        extra_keys = tuple(sorted(runtime_keys - default_keys))

    if missing_keys:
        status = STATUS_CANDIDATE_FOR_MIGRATION
        detail = (
            "в дефолте появились ключи верхнего уровня, которых нет в рабочей копии: "
            + ", ".join(missing_keys)
        )
    else:
        status = STATUS_RUNTIME_CHANGED
        detail = "содержимое рабочей копии отличается от дефолта (ключи верхнего уровня те же)"

    return ContractDriftEntry(
        name=name,
        default_path=default_path,
        runtime_path=runtime_path,
        status=status,
        missing_keys_in_runtime=missing_keys,
        extra_keys_in_runtime=extra_keys,
        detail=detail,
    )


def _default_path_for(runtime_path: Path) -> Path | None:
    """Вычисляет путь дефолта по пути рабочей копии.

    Опирается на то, что рабочий путь и путь дефолта отличаются только корнем
    (``settings.RUNTIME_CONTRACTS_DIR`` vs ``settings.DEFAULT_CONTRACTS_DIR``),
    а относительная часть (под-директория + имя файла) — общая; см.
    ``get_contract_path`` в ``config/settings.py``. Тот же прием уже используется
    в проекте для директорий agent skills (``apps/ai/skills_service.py``,
    ``_contract_skill_roots``), поэтому это не новая идея, а переиспользование
    существующего соглашения.

    Если рабочий путь переопределен переменной окружения (`LOCAL_BUSINESS_*_FILE`
    в `.env`) и больше не лежит под ``RUNTIME_CONTRACTS_DIR``, дефолт вычислить
    нельзя — сравнение для этого контракта пропускается, а не падает.
    """
    try:
        relative = runtime_path.relative_to(settings.RUNTIME_CONTRACTS_DIR)
    except ValueError:
        return None
    return settings.DEFAULT_CONTRACTS_DIR / relative


def _iter_registered_contracts():
    """Файловые контракты из единого реестра Settings Center.

    Источник — ``apps.settings_center.registry.get_registry()``: он уже
    перечисляет все контракты, которыми управляет Settings Center (имя,
    ``storage_kind``, ``metadata.settings_path`` — атрибут ``settings.*`` с
    рабочим путем, — и валидатор), и обслуживает 17 файловых контрактов
    (core/workorders/ai/memory). Отдельный реестр ``apps.core.contract_store``
    сейчас обслуживает только 3 контракта (role_rules, workflow_rules,
    workorder_status_colors) — он уже беднее, чем settings_center.registry, и
    не несет пути дефолта. Поэтому именно settings_center.registry выбран как
    единственный источник маппинга "имя -> путь", а не заведен третий список.
    Дескрипторы без ``metadata.settings_path`` (например, `memory.source.acl_mode`,
    `memory.secret.external_vault_link`) не привязаны к JSON-файлу и пропускаются.
    """
    for descriptor in get_registry().all():
        if descriptor.storage_kind != "runtime_contract":
            continue
        settings_path = descriptor.metadata.get("settings_path")
        if not settings_path:
            continue
        yield descriptor.setting_id, settings_path


def collect_contract_drift() -> list[ContractDriftEntry]:
    """Собирает отчет о дрейфе default vs runtime по всем контрактам реестра."""
    entries = []
    for setting_id, settings_path in _iter_registered_contracts():
        runtime_path = Path(getattr(settings, settings_path))
        default_path = _default_path_for(runtime_path)
        if default_path is None:
            entries.append(
                ContractDriftEntry(
                    name=setting_id,
                    default_path=None,
                    runtime_path=runtime_path,
                    status=STATUS_ENV_OVERRIDE,
                    detail=(
                        f"{settings_path} переопределен переменной окружения и не лежит "
                        "под RUNTIME_CONTRACTS_DIR; сравнение с дефолтом пропущено."
                    ),
                )
            )
            continue
        entries.append(evaluate_contract_drift(setting_id, default_path, runtime_path))
    return sorted(entries, key=lambda entry: entry.name)


def has_reportable_drift(entries) -> bool:
    """True, если хотя бы один контракт отличается от дефолта (любой из двух видов)."""
    return any(entry.is_drift for entry in entries)


def format_contract_drift_report(entries) -> str:
    """Человекочитаемый отчет для команды ``validate_architecture_contracts``.

    Печатается всегда (дрейф — не ошибка команды), поэтому текст явно указывает,
    что штатное состояние проекта может включать ``STATUS_RUNTIME_CHANGED``.
    """
    if not entries:
        return "Дрейф default/runtime контрактов: реестр контрактов пуст."

    lines = ["Дрейф контрактов (contracts/ дефолт <-> data/contracts/ рабочая копия):"]
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
        line = f"  - {entry.name}: {entry.label}"
        if entry.status == STATUS_CANDIDATE_FOR_MIGRATION:
            line += " [" + ", ".join(entry.missing_keys_in_runtime) + "]"
        lines.append(line)

    summary = ", ".join(
        f"{_STATUS_LABELS.get(status, status)} — {count}"
        for status, count in sorted(counts.items())
    )
    lines.append(f"Итого ({len(entries)} контрактов): {summary}.")

    candidates = [entry for entry in entries if entry.status == STATUS_CANDIDATE_FOR_MIGRATION]
    if candidates:
        lines.append(
            "Внимание: для контрактов выше в дефолте появились новые ключи верхнего уровня, "
            "которых нет в рабочей копии — перенесите значения вручную через Settings Center "
            "(см. docs/guides/SETTINGS_CENTER_OPERATIONS.md, раздел 'Дрейф default/runtime')."
        )
    return "\n".join(lines)
