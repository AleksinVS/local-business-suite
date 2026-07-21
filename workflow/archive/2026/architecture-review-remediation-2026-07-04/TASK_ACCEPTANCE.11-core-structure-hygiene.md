# Приёмка: 11-core-structure-hygiene

Дата: 2026-07-07.
Роли: исполнитель — субагент (Opus); независимая проверка — не требуется
(`independent_verification: false`, риск low); code-review и приёмка —
агент-оркестратор.

## Вердикт

**Принят.** Разнос валидаторов и разбиение тестов выполнены механически, без
изменения логики; collect-count совпал, полный регресс зелёный.

## Часть A — разнос валидаторов

- **`apps/core/json_utils.py`: 2131 → 103 строки**, 0 определений `validate_*`.
  Остались только примитивы: `pretty_json`, `load_json_file`, `atomic_write_json`
  + общие хелперы `_ensure_*`.
- **Перенос по доменам** (логика не менялась — non-goal):
  - `apps/ai/contracts.py` — все `validate_ai_*` + приватные + константы;
  - `apps/memory/contracts.py` — все `validate_memory_*` + приватные + константы;
  - `apps/analytics/contracts.py` — `validate_analytics_*` + `validate_dataset_registry_payload`;
  - `apps/workorders/contracts.py` — role_rules / workflow_rules / status_colors;
  - `apps/core/contracts.py` (новый) — `validate_integration_registry_payload`,
    `validate_task_brief_payload`, `validate_change_plan_payload` (core-workflow
    артефакты и SDK-реестр внешних систем, не доменные — обосновано в отчёте).
- **Circular import не создан:** `json_utils.py` НЕ получил top-level re-export
  из `apps.*` (сломал бы ранний импорт `config/settings.py:7` →
  AppRegistryNotReady). Импортёры обновлены напрямую: `validate_architecture_contracts`,
  `contract_services`, `generate_change_plan` + найденные грепом
  `apps/core/forms.py`, `apps/core/contract_store.py`, `apps/core/tests.py`.
  Проверено: `from apps.core.json_utils import validate_*` не осталось нигде.
- Новые `contracts.py` тянут из `json_utils` только чистые примитивы (json_utils —
  лист, обратной зависимости нет).

## Часть B — разбиение тестов

- `apps/memory/tests.py` (2738) → пакет `apps/memory/tests/` (9 тематических
  модулей + `_common.py` + `__init__.py`, ре-экспорт фабрик для
  `apps/filehub/tests.py` — filehub не тронут).
- `apps/ai/tests.py` (2665) → пакет `apps/ai/tests/` (7 модулей + `_common.py`);
  `tests_context_processors.py` перенесён внутрь как `test_context_processors.py`
  (разрешён конфликт test-discovery), относительные импорты и локальные импорты
  валидаторов (`apps.ai.contracts`) переписаны. Имена тестов сохранены 1:1
  (включая добавленные пакетами 05/09).
- **collect-count: 430 до == 430 после** (Django `build_suite`); дополнительно
  AST-сверка 191 метода по (класс, метод).
- Одна правка тела теста: `MemoryDataStoreStubTests.test_debt_markers_present`
  использовал `Path(__file__).parent` (сломался от переезда на уровень глубже) —
  исправлен на `Path(apps.memory.__file__).parent`, семантика 1:1.

## Acceptance-проверки

- `.venv/bin/python manage.py test` (полный) → **Ran 430 tests, OK** (исполнитель).
- Оркестратор дополнительно: `check` (import-smoke всех приложений),
  `validate_architecture_contracts` (гоняет все перенесённые валидаторы),
  collect-count разбитых пакетов, тесты importer-приложений
  (core/settings_center/analytics/workorders).
- `wc -l apps/core/json_utils.py` → **103** (было 2131).

## Замечание по слоям (follow-up, не блокер)

После переноса `apps/core/contract_store.py` (реестр 3 контрактов) и
`apps/core/forms.py` (форма role_rules) импортируют `apps.workorders.contracts`.
Направление core→domain — допустимое «оркестрация → домен» (запрещённое
domains → core-god-module устранено: json_utils больше не знает доменных правил).
Более чистая развязка — реестр с регистрацией валидаторов доменами (без прямого
импорта в core) — кандидат в отдельную задачу, вне scope механического переноса.

## Отложено в backlog (разрешено non-goals)

- `apps/workorders/tests.py` (1101) и `apps/core/tests.py` (1666) не разбиты.
- `apps/ai/tests/test_views.py` — один класс `AIViewsTests` ~1400 строк (сокращается
  только разбиением самого класса). Кандидаты на будущую гигиену тестов.
