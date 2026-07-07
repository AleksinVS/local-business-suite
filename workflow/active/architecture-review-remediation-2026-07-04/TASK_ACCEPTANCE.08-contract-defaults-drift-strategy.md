# Приёмка: 08-contract-defaults-drift-strategy

Дата: 2026-07-07.
Роли: исполнитель — субагент (Sonnet); независимая проверка — не требуется
(`independent_verification: false`, риск medium); code-review и приёмка —
агент-оркестратор.

## Вердикт

**Принят.** Замечаний, требующих доработки, нет; одна известная граница
покрытия зафиксирована ниже.

## Что проверено

Исполнение (executor report + code-review оркестратором):

- Новый модуль `apps/core/contract_drift.py` — только диагностика, без
  автослияния (non-goal соблюдён). Для каждого контракта три исхода:
  `identical` / `runtime_changed` (ожидаемо, не ошибка) / `candidate_for_migration`
  (в дефолте появился ключ верхнего уровня, отсутствующий в рабочей копии —
  самый ценный сигнал). Плюс аккуратная обработка `env_override` (путь
  переопределён переменной окружения → сравнение пропускается, не падает) и
  `unreadable` (файл отсутствует/битый) — эти два не считаются «дрейфом» и не
  проваливают `--fail-on-drift`.
- **Консистентность с системой:** хеш и нормализация переиспользуют
  `apps.core.contract_store.normalized_hash` (тот же хеш, что у оптимистической
  записи в `apply_contract_payload`), чтение — `json_utils.load_json_file`.
  Отчёт считает не по-своему.
- **Единый реестр:** источник маппинга «имя → путь» — `settings_center.registry`
  `get_registry()` (17 файловых `runtime_contract`), путь дефолта выводится из
  runtime-пути через `RUNTIME_CONTRACTS_DIR`/`DEFAULT_CONTRACTS_DIR` (то же
  соглашение, что `get_contract_path` в settings и agent skills). Второй список
  не заведён — как и требовал пакет.
- Команда `validate_architecture_contracts` печатает отчёт **всегда** после
  штатной валидации; `--fail-on-drift` даёт ненулевой код только при реальном
  дрейфе. Документация — новый раздел «Дрейф default/runtime» в
  `SETTINGS_CENTER_OPERATIONS.md` (три состояния + ручной перенос кандидата).
- `.desc.json` + PROJECT_STRUCTURE.yaml (`make gen-struct`) регистрируют модуль.

## Acceptance-проверки (прогнаны оркестратором)

- `.venv/bin/python manage.py validate_architecture_contracts` → exit 0,
  отчёт по всем 17 контрактам (10 identical, 7 runtime_changed, 0 кандидатов).
- `.venv/bin/python manage.py validate_architecture_contracts --fail-on-drift`
  → exit 1 (в dev есть ожидаемый дрейф) — флаг работает.
- `.venv/bin/python manage.py test apps.core.tests` → **Ran 62 tests, OK**.
- `.venv/bin/python manage.py check` → без ошибок.

## Известная граница покрытия (не дефект)

Вне отчёта остаются 8 аналитических контрактов и `integrations/registry.json`:
они не зарегистрированы ни в `settings_center.registry`, ни в `contract_store`
(не редактируются через Settings Center). Расширение охвата потребовало бы
сперва зарегистрировать их в реестре, а не заводить третий список путей —
осознанное решение исполнителя, согласуется с духом пакета (не плодить реестры).
Кандидат в отдельную задачу, если для этих контрактов понадобится диагностика
дрейфа.

## Замечание по ordering (в рекомендацию)

Модуль импортирует `validate_ai_tools_drift`/`load_json_file` из
`apps/core/json_utils.py`, который будет разбит пакетом 11 (json_utils split).
Пакет 11 должен учесть эти импорты (и импорт `load_json_file` в
`contract_drift.py`) при переносе. Зафиксировано для исполнителя пакета 11.
