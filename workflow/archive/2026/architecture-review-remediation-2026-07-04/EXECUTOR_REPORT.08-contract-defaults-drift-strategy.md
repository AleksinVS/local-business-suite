# Executor Report: 08-contract-defaults-drift-strategy

Дата: 2026-07-07.
ADR: `docs/adr/ADR-0031-runtime-contract-store-and-delivery.md` (раздел «Решение» п.4
«Диагностика дрейфа default↔runtime»).

## Что сделано

### 1. Новый модуль `apps/core/contract_drift.py`

Диагностика дрейфа default (`contracts/`) vs runtime (`data/contracts/`) по всем контрактам,
которыми управляет `apps.settings_center.registry`. Не сливает и не перезаписывает файлы —
только читает и сравнивает (non-goal автослияния соблюден).

- `evaluate_contract_drift(name, default_path, runtime_path)` — сравнение двух конкретных
  файлов; не зависит от реестра, поэтому тестируется на произвольных временных файлах.
- `collect_contract_drift()` — берет список контрактов из `get_registry()`, для каждого
  вычисляет путь дефолта из пути рабочей копии (см. «Выбор реестра» ниже) и вызывает
  `evaluate_contract_drift`.
- Три исхода на контракт (`STATUS_IDENTICAL`, `STATUS_RUNTIME_CHANGED`,
  `STATUS_CANDIDATE_FOR_MIGRATION`) + два вспомогательных состояния для надежности
  (`STATUS_ENV_OVERRIDE` — путь переопределен `.env`, сравнение с дефолтом невозможно;
  `STATUS_UNREADABLE` — файл отсутствует/битый JSON, чтобы отчет не падал при аномалии).
- Сравнение: (а) множество ключей верхнего уровня, (б) `apps.core.contract_store.normalized_hash`
  (тот же sha256 от `pretty_json(sort_keys=True)`, что использует оптимистическая проверка
  записи в `contract_services.apply_contract_payload`) — переиспользование существующей
  утилиты хеширования/нормализации, как требовала постановка.
- `has_reportable_drift(entries)` и `format_contract_drift_report(entries)` — для команды.

### 2. Расширение `validate_architecture_contracts`

- Добавлен `--fail-on-drift` (`add_arguments`).
- После существующей семантической валидации (`Architecture contracts are valid.`) команда
  всегда печатает отчет `collect_contract_drift()` / `format_contract_drift_report()`.
- Дрейф не ошибка: exit code остается 0. Только при `--fail-on-drift` и наличии
  `STATUS_RUNTIME_CHANGED`/`STATUS_CANDIDATE_FOR_MIGRATION` команда поднимает `CommandError`
  (ненулевой код) — для CI-сценариев, которым нужна полная синхронность с дефолтом.

### 3. Тесты (`apps/core/tests.py`, класс `ContractDriftTests`)

Изолированы от реального состояния `data/contracts/` (оно и само содержит ожидаемый дрейф —
см. «Фактический вывод команды» ниже) через прямой вызов `evaluate_contract_drift` на временных
файлах либо через `unittest.mock.patch` на `collect_contract_drift` для теста команды:

| Пункт пакета | Тест |
| --- | --- |
| Искусственный дрейф (новый ключ в дефолте) → кандидат на перенос | `test_new_default_key_is_reported_as_migration_candidate` |
| Идентичные файлы → нет дрейфа (устойчиво к форматированию/порядку ключей) | `test_identical_files_report_no_drift` |
| `--fail-on-drift` → ненулевой код при дрейфе, 0 при отсутствии | `test_fail_on_drift_flag_exits_nonzero_only_when_drift_present` |

Дополнительно (не требовалось явно, но покрывает регресс реестра):

- `test_runtime_value_change_without_new_keys_is_expected_not_a_candidate` — правка значения
  существующего ключа в рабочей копии классифицируется как `STATUS_RUNTIME_CHANGED`
  (ожидаемо), а не как кандидат — граница между двумя видами дрейфа из постановки.
- `test_collect_contract_drift_covers_settings_center_registry_contracts` — `collect_contract_drift()`
  покрывает ровно те контракты реестра, у которых `storage_kind == "runtime_contract"` и задан
  `metadata.settings_path` (защита от молчаливого выпадения контракта из отчета при будущих
  правках реестра).

### 4. Документация

`docs/guides/SETTINGS_CENTER_OPERATIONS.md` — новый раздел «Дрейф default/runtime»: что
означают три статуса, как перенести кандидата вручную через Settings Center, флаг
`--fail-on-drift`, методологическая заметка (почему не автослияние).

### Структура

- `apps/core/.desc.json` — запись про `contract_drift.py`.
- `make gen-struct` прогнан, `PROJECT_STRUCTURE.yaml` обновлен (1 новая строка).

## Выбор реестра: `settings_center.registry`, а не `contract_store`

Постановка требовала переиспользовать существующий реестр «имя → default path / runtime path /
валидатор» и не плодить второй список. В кодовой базе есть два кандидата:

- `apps.core.contract_store._CONTRACTS` — обслуживает только **3** контракта (`role_rules`,
  `workflow_rules`, `workorder_status_colors`); хранит только `path_setting` (имя атрибута
  `settings.*` с runtime-путем) и валидатор — путь дефолта не несет вообще.
- `apps.settings_center.registry.get_registry()` — единый список дескрипторов, которым Settings
  Center уже пользуется для чтения/записи UI; **17** дескрипторов с `storage_kind ==
  "runtime_contract"` и `metadata.settings_path` (core: 2, workorders: 1, ai: 5, memory: 9).
  Тоже не хранит путь дефолта явно как отдельное поле.

Выбран `settings_center.registry`: он шире (17 контрактов вместо 3) и это тот же реестр, что
Settings Center уже использует для контрактов, редактируемых через UI. Путь дефолта вычисляется
из runtime-пути тем же приемом, что уже применяется в проекте для agent skills
(`apps/ai/skills_service.py::_contract_skill_roots`): `runtime_path` и `default_path` отличаются
только корнем (`settings.RUNTIME_CONTRACTS_DIR` vs `settings.DEFAULT_CONTRACTS_DIR`), а
относительная часть (под-директория + имя файла) общая — `default_path =
DEFAULT_CONTRACTS_DIR / runtime_path.relative_to(RUNTIME_CONTRACTS_DIR)`. Если путь
переопределен переменной окружения и больше не лежит под `RUNTIME_CONTRACTS_DIR`, сравнение
для этого контракта помечается `STATUS_ENV_OVERRIDE`, а не падает.

**Не покрыто** (осознанно, чтобы не заводить третий список): 8 analytics-контрактов
(`contracts/analytics/*.json`) и `contracts/integrations/registry.json` управляются через
`get_contract_path` в `config/settings.py`, но не зарегистрированы ни в `settings_center.registry`,
ни в `contract_store` — они не редактируются через Settings Center UI. Если для них тоже нужен
отчет о дрейфе, естественный следующий шаг — сначала зарегистрировать их как дескрипторы
`settings_center` (или явно решить, что они вне UI-контура), а не вводить отдельный реестр путей
для `contract_drift.py`.

## Команды проверок и фактические результаты

1. `.venv/bin/python manage.py validate_architecture_contracts`

   ```text
   Architecture contracts are valid.

   Дрейф контрактов (contracts/ дефолт <-> data/contracts/ рабочая копия):
     - ai.contract.chat_settings: совпадает с дефолтом
     - ai.contract.models: рабочая копия изменена (ожидаемо, не ошибка)
     - ai.contract.registry: рабочая копия изменена (ожидаемо, не ошибка)
     - ai.contract.task_types: совпадает с дефолтом
     - ai.contract.tools: совпадает с дефолтом
     - core.contract.role_rules: совпадает с дефолтом
     - core.contract.workflow_rules: совпадает с дефолтом
     - memory.contract.claims_policy: рабочая копия изменена (ожидаемо, не ошибка)
     - memory.contract.file_organization_profiles: совпадает с дефолтом
     - memory.contract.graph_schema: совпадает с дефолтом
     - memory.contract.ingestion_profiles: рабочая копия изменена (ожидаемо, не ошибка)
     - memory.contract.profiles: рабочая копия изменена (ожидаемо, не ошибка)
     - memory.contract.retrieval_budget: рабочая копия изменена (ожидаемо, не ошибка)
     - memory.contract.routing: совпадает с дефолтом
     - memory.contract.sources: рабочая копия изменена (ожидаемо, не ошибка)
     - memory.contract.trust_policy: совпадает с дефолтом
     - workorders.contract.status_colors: совпадает с дефолтом
   Итого (17 контрактов): совпадает с дефолтом — 10, рабочая копия изменена (ожидаемо, не ошибка) — 7.
   ```

   Exit code: 0. **Реальный дрейф в этой рабочей копии репозитория обнаружен** (7 из 17
   контрактов) — все относятся к `STATUS_RUNTIME_CHANGED` (набор ключей верхнего уровня тот же,
   значения отличаются), кандидатов на перенос (`STATUS_CANDIDATE_FOR_MIGRATION`) сейчас нет.
   Это ожидаемое dev-stage состояние, не ошибка данного пакета — команда его ранее просто не
   видела.

2. `.venv/bin/python manage.py validate_architecture_contracts --fail-on-drift`

   Завершается `CommandError` (exit code 1) — подтверждено вручную; в тестах поведение флага
   проверено детерминированно через `unittest.mock.patch` (не зависит от того, есть ли сейчас
   реальный дрейф в рабочих копиях этой установки).

3. `.venv/bin/python manage.py test apps.core.tests`

   ```text
   Ran 62 tests in 38.140s
   OK
   ```

4. `.venv/bin/python manage.py test apps.settings_center apps.ai.tests` (regression по соседним
   доменам, не входит в write_scope, но использует `settings_center.registry`)

   ```text
   Ran 110 tests in 166.318s
   OK
   ```

5. `.venv/bin/python manage.py check`

   ```text
   System check identified no issues (0 silenced).
   ```

## Методологическая заметка (для обучающего контура)

Дефолты (`contracts/`, git) и рабочие копии (`data/contracts/`, редактируются через Settings
Center) намеренно разделены — это тот же паттерн, что «конфиг по умолчанию в пакете» vs
«конфиг администратора» в любой серверной системе (nginx `*.conf.default`, PostgreSQL
`postgresql.conf.sample`, Kubernetes ConfigMap с defaults + override). Копировать дефолт при
первом запуске и потом не трогать — стандартная и правильная практика: она защищает
осознанные локальные настройки от перезаписи git-обновлением. Проблема начинается там, где
это копирование выдают за «синхронизацию» и забывают, что после первого раза дефолт и рабочая
копия — это два независимых файла, которые расходятся молча.

Отсюда два принципиально разных вопроса, которые нельзя схлопывать в один:

- **«Рабочая копия отличается от дефолта?»** — да почти всегда, и это нормально: администратор
  настроил роли под свою организацию, отредактировал memory-профили под свой корпус документов.
  Диагностировать это как ошибку было бы шумом, который никто не будет читать.
- **«В дефолте появилась новая опция, которой нет в рабочей копии?»** — это другой по своей
  природе сигнал: не расхождение значений, а расширение схемы контракта в коде, которое молча
  не долетело до уже работающей установки. Именно поэтому в отчете это выделено в отдельный,
  самый заметный статус (`STATUS_CANDIDATE_FOR_MIGRATION`) — «появился новый ключ» и «значение
  существующего ключа изменили» требуют разных действий человека (перенести новую опцию vs
  ничего не делать), и автоматика не должна принимать это решение за него: тихий merge мог бы
  затереть намеренную настройку, а тихое игнорирование — оставить старую установку без
  функциональности, которая уже есть в коде, без единого предупреждения. Отчет поэтому только
  диагностирует и называет решение человеку, а не выполняет его сам.

## Ограничения и остаточные риски

- Отчет покрывает только контракты, зарегистрированные в `settings_center.registry` (17 из
  всех `get_contract_path`-управляемых файлов в проекте). Analytics (8 файлов) и
  `integrations/registry.json` не покрыты — см. «Выбор реестра» выше; если это потребуется,
  естественный путь — сначала добавить им дескрипторы в `settings_center`, а не третий реестр
  путей внутри `contract_drift.py`.
- Сравнение — только по ключам **верхнего уровня**. Изменение внутри существующего вложенного
  объекта (например, новый ключ внутри `role_rules.manager.*`) не порождает
  `STATUS_CANDIDATE_FOR_MIGRATION`, а попадает в `STATUS_RUNTIME_CHANGED` — соответствует
  явной постановке задачи («ключи верхнего уровня»), но при появлении важной вложенной опции
  сигнал будет слабее, чем для опции верхнего уровня. Это осознанное ограничение non-goal
  («не вводить обязательную схему версий») — более глубокий диф потребовал бы понятия схемы
  на уровень ниже, что явно исключено из пакета.
- `STATUS_ENV_OVERRIDE`/`STATUS_UNREADABLE` не считаются дрейфом для `--fail-on-drift` (флаг
  реагирует только на `STATUS_RUNTIME_CHANGED`/`STATUS_CANDIDATE_FOR_MIGRATION`) — если в CI
  важно также ловить «путь переопределен окружением» или «рабочий файл битый», это отдельное
  расширение флага, не запрошенное постановкой явно.
- Автоматического переноса кандидатов в рабочую копию нет и не планируется этим пакетом
  (non-goal) — операция остается ручной через Settings Center; описано в
  `docs/guides/SETTINGS_CENTER_OPERATIONS.md`.
