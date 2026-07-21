# Executor report: 11-core-structure-hygiene

Дата: 2026-07-07
Исполнитель: Claude agent (executor)
Пакет: `workflow/archive/2026/architecture-review-remediation-2026-07-04/task-packets/11-core-structure-hygiene.json`

Цель: (A) `apps/core/json_utils.py` содержит только универсальные примитивы,
доменные валидаторы контрактов переехали в свои приложения (конфликт правил 3 и 5
AGENTS.md); (B) крупнейшие монолитные `tests.py` разбиты на пакеты `tests/` по темам.

## Итог по acceptance

- `apps/core/json_utils.py`: **2131 → 103 строки** (только примитивы).
- `manage.py check` — без ошибок.
- `manage.py validate_architecture_contracts` — работает, **exit 0**.
- collect-count (Django `build_suite`): **430 до == 430 после**.
- полный `manage.py test`: первый прогон `Ran 430`, 1 падение (см. ниже, устранено);
  повторный прогон — `Ran 430 ... OK` (зелёный).
- `grep "from apps.core.json_utils import"` по `apps/ config/ services/` — среди
  импортов **нет доменных `validate_*`**, только примитивы (`load_json_file`,
  `pretty_json`, `atomic_write_json`).

## Часть A — разнос валидаторов

### Куда какой валидатор переехал

**`apps/ai/contracts.py`** (реестр, инструменты, типы задач, чат, семантические
кросс-проверки):
`validate_ai_registry_payload`, `validate_ai_tools_payload`,
`validate_ai_task_types_payload`, `validate_ai_chat_settings_payload`
(+ приватный `_validate_ai_chat_settings_block`), `validate_ai_tools_drift`,
`validate_ai_task_types_tool_alignment`, `validate_ai_write_confirmation_alignment`,
`validate_ai_task_types_slot_coverage`, `validate_ai_identity_model_alignment`.
Константы `REQUIRED_AI_*`, `AI_CHAT_*_VALUES`, `IDENTITY_MINIMUM_FIELDS`.

**`apps/memory/contracts.py`**:
`validate_memory_sources_payload`, `validate_memory_trust_policy_payload`,
`validate_memory_claims_policy_payload`, `validate_memory_retrieval_budget_payload`,
`validate_memory_ingestion_profiles_payload`,
`validate_memory_file_organization_profiles_payload`,
`validate_memory_graph_schema_payload`, `validate_memory_profiles_payload`,
`validate_memory_routing_payload` (+ приватные `_validate_memory_source_trust_fields`,
`_validate_memory_source_policy_fields`, `_validate_trust_rule`,
`_path_looks_absolute_or_unc`). Все константы `REQUIRED_MEMORY_*`,
`OPTIONAL_MEMORY_*`, `MEMORY_*_VALUES`.

**`apps/analytics/contracts.py`**:
`validate_dataset_registry_payload` и все `validate_analytics_*` (sources,
scope_rules, business_facts, metrics, monitors, diagnostic_playbooks,
workflow_routes, dedup_rules, retention_profiles). Константы `REQUIRED_DATASET_KEYS`,
`REQUIRED_ANALYTICS_*`, `ANALYTICS_*_VALUES`.

**`apps/workorders/contracts.py`**:
`validate_role_rules_payload`, `validate_workflow_rules_payload`,
`validate_workorder_status_colors_payload`. Константы `ROLE_SCOPE_VALUES`,
`REQUIRED_ROLE_KEYS`, `BACKWARD_COMPAT_ROLE_DEFAULT_KEYS`, `REQUIRED_WORKFLOW_KEYS`.

### Решение по неоднозначным валидаторам → `apps/core/contracts.py`

`validate_integration_registry_payload`, `validate_task_brief_payload`,
`validate_change_plan_payload` вынесены в **новый `apps/core/contracts.py`** (не в
доменное приложение). Обоснование:

- `task_brief` и `change_plan` — артефакты агентного workflow (task packets,
  `generate_change_plan`), относятся к процессу разработки, а не к бизнес-домену
  memory/ai/analytics/workorders.
- `integration_registry` — это **общий** реестр внешних систем уровня SDK/транспорта
  (правило 3: «Общий список внешних систем хранится в
  `contracts/integrations/registry.json`»). Валидатор проверяет форму общего реестра,
  а не маппинг внешних данных в конкретную доменную модель — доменный маппинг живёт в
  соответствующих приложениях. Поэтому это core-уровень, а не отдельный домен.

Эти три валидатора — единственное содержимое `apps/core/contracts.py`; он импортирует
из `json_utils` только примитив `_ensure_non_empty_mapping`.

### Что осталось в `json_utils.py` (примитивы)

`pretty_json`, `load_json_file`, `atomic_write_json` и общие внутренние хелперы
`_ensure_non_empty_mapping`, `_ensure_list_of_strings`, `_ensure_contract_list`,
`_ensure_unique_code`, `_ensure_positive_int`, `_ensure_number`. Все новые модули
`contracts.py` импортируют нужные примитивы отсюда (обратной зависимости нет).
Неиспользуемый `import re` удалён.

### Про circular import (config/settings.py)

Учтено. В `json_utils.py` **не добавлялся** top-level re-export вида
`from apps.<app>.contracts import ...` — это затянуло бы загрузку `apps.*` во время
раннего импорта `config/settings.py:7` (`from apps.core.json_utils import
load_json_file`) и уронило бы старт (`AppRegistryNotReady`). Вместо re-export
обновлены сами импортёры. `config/settings.py` правок не потребовал (импортирует
только `load_json_file`). В `json_utils.py` добавлен комментарий-предупреждение.

### Обновлённые импортёры

По плану оркестратора:
- `apps/core/management/commands/validate_architecture_contracts.py` — импорты
  разнесены по 5 новым модулям `contracts.py`;
- `apps/settings_center/contract_services.py` — то же;
- `apps/core/management/commands/generate_change_plan.py` — `validate_task_brief_payload`
  из `apps.core.contracts`.

**Дополнительно найдены `grep`-ом (не были в инвентаризации оркестратора) и обновлены:**
- `apps/core/forms.py` — `validate_role_rules_payload` из `apps.workorders.contracts`;
- `apps/core/contract_store.py` — role/workflow/status_colors из `apps.workorders.contracts`;
- `apps/core/tests.py` — memory-валидаторы из `apps.memory.contracts`; хелпер
  `get_optional_json_validator` теперь резолвит валидатор сначала в
  `apps.memory.contracts`, затем в `json_utils`.

Эти три файла формально были вне `WRITE_SCOPE` пакета, но правка их импортов —
обязательное следствие переноса и прямое требование acceptance («не осталось
`from apps.core.json_utils import validate_*`»). Изменения минимальны — только строки
импорта (+ одна строка в хелпере).

**`settings_descriptors.py` (ai/memory/workorders/core) не трогались:** они ссылаются
на валидаторы **строковыми именами**, которые резолвятся через словарь
`apps.settings_center.contract_services.VALIDATORS`; словарь теперь собирает функции
из новых модулей, ключи-строки не изменились. `apps/core/checks.py` тоже не трогался
(вызывает команду `validate_architecture_contracts`, а не валидаторы напрямую).

Проверено: `grep -rn "from apps.core.json_utils import" apps/ config/ services/` —
доменных `validate_*` среди импортов нет.

### Замечание о направлении зависимостей (честно)

После переноса `apps/core/contract_store.py` и `apps/core/forms.py` импортируют
`apps.workorders.contracts`, а `apps/core/tests.py` — `apps.memory.contracts`, то есть
core начал зависеть от доменных приложений. Это **не** циклический импорт на этапе
старта (проверено: `contract_store`/`forms` грузятся лениво, а доменные `contracts.py`
тянут из `json_utils` только чистые примитивы, которые ничего из `apps.*` не
импортируют). Направление «оркестрация/инфраструктура ядра → домен» допустимо: правила
3/5 запрещают обратное — чтобы **домены** зависели от god-модуля в ядре. Раньше правило
жило в ядре и было скрыто; теперь правило живёт в своём домене, а факт потребления его
ядром стал явным импортом.

## Часть B — разбиение тестов

### `apps/memory/tests.py` (2738 строк) → пакет `apps/memory/tests/`
9 тематических модулей + `_common.py` (общий preamble: импорты, `MemoryModelFactoryMixin`,
хелперы) + `__init__.py`:
- `test_admin_and_review_ui.py` (Admin observability, review UI, pending review)
- `test_ingestion.py` (bootstrap expectations, document ingestion)
- `test_sources_and_models.py` (source model/service, metadata, queue tasks)
- `test_policy_and_privacy.py` (policy/audit, source adapter projection, privacy)
- `test_chat_knowledge.py`
- `test_external_connectors.py`
- `test_indexing.py`
- `test_reconcile_and_edges.py` (repo lock, reconcile, knowledge edges)
- `test_data_store.py`

### `apps/ai/tests.py` (2665 строк) → пакет `apps/ai/tests/`
7 тематических модулей + `test_context_processors.py` + `_common.py` + `__init__.py`:
`test_views.py`, `test_identity_context.py`, `test_trace_context.py`,
`test_semantic_validators.py`, `test_task_type_contract.py`,
`test_identity_model_validation.py`, `test_tool_message_visibility.py`.

### `tests_context_processors.py`
Перенесён **внутрь** пакета как `apps/ai/tests/test_context_processors.py` (классы и
имена сохранены; импорты у него абсолютные — правки не потребовались). Это устраняет
конфликт discovery «`tests.py` + `tests_context_processors.py`», ради которого он раньше
жил отдельным файлом.

### Механика разбиения (как сохранена корректность)
- Разбито **по тест-классам**, имена тестов 1:1, тела не менялись (кроме одного
  вынужденного фикса, см. ниже).
- Относительные импорты пакета приложения перенесены на уровень глубже
  (`from .models` → `from ..models` и т.д.), т.к. модули уехали в подпакет.
- Локальные импорты `from apps.core.json_utils import validate_ai_*` в AI-тестах
  переведены на `from apps.ai.contracts import validate_ai_*`.
- Общий preamble вынесен в `_common.py`; тематические модули берут имена через
  `from apps.<app>.tests._common import *`. `_common.py` не совпадает с шаблоном
  discovery (`test*.py`), поэтому как тест не собирается.
- `apps/memory/tests/__init__.py` реэкспортирует `MemoryModelFactoryMixin` и
  `get_optional_memory_model`, чтобы сохранить публичный путь
  `from apps.memory.tests import MemoryModelFactoryMixin` для внешнего потребителя
  `apps/filehub/tests.py` (его не пришлось править).

### Одно вынужденное изменение тела теста
`MemoryDataStoreStubTests.test_debt_markers_present` определял корень приложения как
`pathlib.Path(__file__).resolve().parent`. После переезда файла на уровень глубже
(`apps/memory/tests/…`) этот путь стал указывать на подпакет `tests/`, а не на корень
приложения — тест находил 1 маркер `DEBT(ADR-0030-5a)` вместо 2 (реальные маркеры в
`chat_memory.py` и `memory_reconcile.py`). Исправлено: корень берётся из пакета
(`pathlib.Path(apps.memory.__file__).resolve().parent`), из скана исключается вся
директория `tests` (`"tests" not in p.parts`) вместо только `tests.py`. Семантика
восстановлена 1:1 (2 маркера 5a, 1 маркер 5b). Имя теста сохранено. Это единственная
правка логики теста, и она обязательна именно из-за переезда файла.

### collect-count до/после
Замерено штатным loader-ом Django (`get_runner(settings).build_suite([])`), т.к.
acceptance-раннер — `manage.py test` (его discovery-паттерн `test*.py` покрывает и
`test_context_processors.py`):

- **ДО:** `Found 430 test(s)` → 430
- **ПОСЛЕ:** `Found 430 test(s)` → 430 — совпало.

Дополнительно сверил число тест-методов через AST в исходных и разбитых файлах:
ai=99, memory=82, context_processors=10 → 191 в оригиналах и 191 в разбиении,
множества `(класс, метод)` совпадают, потерь/дублей нет.

Примечание про `pytest`: у него `python_files = tests.py test_*.py *_tests.py`, поэтому
исходный `tests_context_processors.py` (начинается с `tests_`, а не `test_`) он **не**
собирал; после переименования в `test_context_processors.py` он начнёт попадать в
pytest-сбор. Поэтому для паритета брал именно Django-раннер (авторитетный для
acceptance), а не pytest.

## Backlog (отложено, non-goal это разрешает)
Не разбивались (по мере роста пакета — отдельной задачей):
- `apps/workorders/tests.py` (1101 строка);
- `apps/core/tests.py` (1666 строк).
Кандидат на дальнейшую гранулярность: `apps/ai/tests/test_views.py` — это один класс
`AIViewsTests` (~1400 строк), разбить его можно только дроблением самого класса, что
выходит за рамки «разбить по классам с сохранением имён».

## Документация
Обновлены `.desc.json`: `apps/{ai,memory,analytics,workorders,core}` — добавлены записи
`contracts.py` и (для ai/memory) `tests/`; уточнено описание `apps/core/json_utils.py`
(теперь только примитивы). `make gen-struct` **не запускался** (запрещено пакетом —
регенерирует оркестратор); `PROJECT_STRUCTURE.yaml` не трогался.

## Методическая заметка (обучающий контур)

**Почему ядро (`core`) не должно знать доменные правила (правила 3/5 AGENTS.md).**
Правило 5 (DRY) требует выносить переиспользуемое в `apps.core` — отсюда и вырос
`json_utils.py` на 2131 строку. Но правило 3 (границы доменов) требует, чтобы
бизнес-правила жили в своём домене. Эти правила конфликтуют, если трактовать «валидатор
контракта memory» как «переиспользуемую утилиту». Развязка: переиспользуемое —
это **механика** проверки формы JSON (`_ensure_*`, атомарная запись), а не **знание**
о том, какие поля обязаны быть у memory-source или какие бывают trust-статусы. Когда
доменное знание живёт в ядре, ядро превращается в god-object: любое изменение доменного
контракта заставляет менять `core`, растёт связность, и домены начинают зависеть от
общего модуля-свалки (запрещённое правилом 3 направление). Разнеся валидаторы по
`apps/<domain>/contracts.py`, мы оставили в ядре только доменно-нейтральные примитивы,
а знание вернули владельцу домена. Импорт примитивов из ядра в домен — правильное
направление (домен зависит от стабильной инфраструктуры); обратный импорт (ядро тянет
доменный `contracts.py` в `contract_store`/`forms`) допустим только для
оркестрирующих/инфраструктурных мест ядра и сделан явным, а не скрытым.

**Почему монолитный `tests.py` на 2700 строк мешает.** Навигация: чтобы найти тесты
external-connectors среди 2738 строк, нужно листать весь файл; тематический модуль
`test_external_connectors.py` находится по имени. Ревью: диф по одному большому файлу
смешивает несвязанные изменения, конфликты слияния вероятнее, а рецензент не видит по
структуре, какая подсистема затронута. Изоляция: при падении раннер называет модуль
(`apps.memory.tests.test_indexing`), и сразу понятно, что чинить. Параллельность и
кэш: мелкие модули дешевле перезапускать точечно. Ограничение: дробить нужно по
тест-классам с сохранением имён — иначе теряется история и ломается внешняя адресация
тестов (как здесь `apps.filehub.tests`, импортирующий фикстуру из пакета).
