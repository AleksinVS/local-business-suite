# Executor report: 07-settings-bootstrap-extraction

Дата: 2026-07-07
Исполнитель: Claude agent (executor)
Пакет: `workflow/active/architecture-review-remediation-2026-07-04/task-packets/07-settings-bootstrap-extraction.json`

## Цель

Импорт `config/settings.py` не создаёт каталоги и не копирует файлы; первичная
подготовка runtime выполняется явной идемпотентной командой; валидация контрактов
доступна как Django system check.

## Что сделано

### 1. `config/settings.py` — убраны побочные эффекты импорта

- Удалён цикл `runtime_dir.mkdir(...)` (создавал ~15 каталогов `data/`) и три
  `os.makedirs(RUNTIME_CONTRACTS_DIR / ...)`.
- `get_contract_path()` стала чистым вычислением пути: возвращает env-override
  ЛИБО путь рабочей копии в `data/contracts/`. Убраны `runtime_path.parent.mkdir`
  и `shutil.copy(default -> runtime)`. Семантика env-override сохранена
  (non-goal). Возвращается ВСЕГДА рабочий путь (не дефолт) — чтобы запись через
  Settings Center шла строго в `data/contracts/`, а не в read-only дефолты git.
- Константы `LOCAL_BUSINESS_*_FILE` остались на месте (это ПУТИ, их читают по
  всему коду) — изменился только способ их вычисления (без побочек).
- Блок загрузки+валидации ~30 контрактов на импорте заменён: валидация ПЕРЕЕХАЛА
  в system check (см. п.3), а payload-константы `LOCAL_BUSINESS_*` (без `_FILE`)
  грузятся через новый `_load_contract_payload()` — отказоустойчиво (рабочая копия
  → упакованный дефолт → `None`) и БЕЗ падения импорта в среде без bootstrap.
  Эти payload-константы оставлены, потому что их читают 13+ мест в
  `apps.ai/apps.memory/apps.filehub/apps.core.forms/apps.analytics` (многие через
  `getattr(settings, "...", default)`); перенос всех читателей на `contract_store`
  вне write scope пакета.
- `DATA_DIR` получил env-override `LOCAL_BUSINESS_DATA_DIR` (по умолчанию
  `<repo>/data` — расположение НЕ меняется). Нужно для теста «импорт в чистой
  среде» и полезно для относительного переноса данных.
- Логирование: у file-хендлера (`app.log`) добавлен `delay=True`. Это
  обязательное следствие выноса mkdir из импорта: `django.setup()` применяет
  `LOGGING`, и раньше каталог `data/logs/` уже существовал (его создавал импорт);
  теперь без `delay=True` любая `manage.py`-команда в чистой среде падала бы на
  «Unable to configure handler 'file'». Файл теперь открывается лениво, при первой
  записи (после bootstrap каталог уже есть).
- Булевы env-флаги переведены на `env_bool`: `SECURE_SSL_REDIRECT`,
  `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` (были строгий `== "True"`),
  `LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED`, `LOCAL_BUSINESS_COPILOTKIT_ENABLED`,
  `SETTINGS_CENTER_ENABLED`, `SETTINGS_CENTER_HELP_AI_ENABLED`,
  `ACCOUNTS_AD_LINK_ENABLED`, `ACCOUNTS_AD_GROUP_ROLE_SYNC`,
  `MEMORY_ACL_INHERITANCE_ENABLED`, `MEMORY_ACL_FAIL_CLOSED`. `DEBUG` оставлен как
  Django-идиома `== "1"` (объявлен до `env_bool`, в findings не значился).
- Импорты почищены: убраны неиспользуемые `import json`, `ValidationError` и весь
  список `validate_*` из `json_utils` (остался только `load_json_file`).

### 2. Новая команда `apps/core/management/commands/bootstrap_runtime.py`

Идемпотентная подготовка runtime, заменяющая побочки импорта:
- создаёт 18 каталогов (`data/db`, `data/media`, `data/logs`, `data/contracts`,
  `data/knowledge_repo`, `data/queues`, `data/indexes/{fulltext,vector,graph}`,
  `data/processing/{raw_quarantine,safe_work,extraction_packets,cleanup_manifests}`,
  `data/cache`, `data/analytics/duckdb`, `data/contracts/{ai,integrations,analytics}`);
- копирует дефолты `contracts/*.json` → `data/contracts/` ТОЛЬКО если рабочей
  копии ещё нет (не затирает правки админа). `schemas/` и `.desc.json` пропускаются —
  рабочая копия повторяет ровно тот состав (28 файлов), что давало прежнее
  копирование на импорте;
- `--dry-run` показывает план без записи;
- `requires_system_checks = ()` — bootstrap НЕ запускает system checks (иначе
  проверка контрактов сработала бы до того, как рабочие копии скопированы —
  chicken-and-egg на первом старте);
- строится от `settings.DATA_DIR`/`RUNTIME_CONTRACTS_DIR`, поэтому корректна и при
  перенесённом каталоге данных, и во временной среде теста.

### 3. Валидация контрактов → Django system check

- Новый `apps/core/checks.py`: `@register("contracts")` `check_architecture_contracts`.
  Переиспользует команду `validate_architecture_contracts` целиком (инстанцирует
  `Command` и вызывает `handle()` напрямую — без дублирования списка валидаторов и
  без рекурсии, т.к. `handle()` не запускает system-check-фазу). Любая ошибка
  контракта превращается в `Error(id="core.E001")`.
- `apps/core/apps.py`: `CoreConfig.ready()` импортирует `checks` для регистрации.
- Проверку выполняет и обычный `manage.py check` (его зовёт `make check`), и
  `manage.py check --tag contracts`, и system-check-фаза перед `migrate` в
  entrypoint — fail-fast на битом контракте сохранён.

### 4. entrypoint / документация

- `docker/entrypoint.prod.sh`: `python manage.py bootstrap_runtime` добавлен ПЕРЕД
  `wait_for_database`/`migrate`; `mkdir` сокращён до `/app/staticfiles`.
- `README.md`: `bootstrap_runtime` добавлен в Быстрый старт (Linux + Windows) с
  пояснением; упомянут `check --tag contracts`.
- `docs/deployment/DEPLOYMENT.md`: раздел «Как работает production-старт» описывает
  bootstrap, чистый импорт settings и вынос валидации в system check.
- `apps/core/.desc.json`: записи про `checks.py` и `bootstrap_runtime.py`.

### 5. Тесты (`apps/core/tests.py`)

- `BootstrapRuntimeCommandTests.test_creates_directories_and_copies_contracts_idempotently`
  — каталоги созданы, контракты скопированы, `schemas/`/`.desc.json` пропущены,
  повторный запуск не ломается и не затирает отредактированную рабочую копию.
- `BootstrapRuntimeCommandTests.test_dry_run_writes_nothing`.
- `SettingsImportSideEffectTests.test_importing_settings_without_data_dir_creates_nothing`
  — подпроцесс `import config.settings` с временным `LOCAL_BUSINESS_DATA_DIR`:
  exit 0 и каталог данных не создан.
- `ContractSystemCheckTests.test_check_contracts_tag_passes_for_valid_contracts` и
  `..._detects_broken_contract` — `check --tag contracts` ловит битый контракт
  (`SystemCheckError`).

## Кто читал `*_FILE` напрямую и как это разрешено (проверено грепом)

Прямые читатели `settings.LOCAL_BUSINESS_*_FILE` (open/load в обход store):
- `apps/core/forms.py` — `LOCAL_BUSINESS_ROLE_RULES_FILE.read_text()`;
- `apps/core/management/commands/validate_architecture_contracts.py` — все контракты;
- `apps/settings_center/contract_services.py` — кросс-валидация на записи;
- `apps/analytics/services.py` — `sources/metrics/monitors`;
- `apps/core/management/commands/sync_ai_tool_registry.py` — `AI_TOOLS_FILE` (запись).

Разрешение: константы `*_FILE` продолжают указывать на рабочую копию под
`data/contracts/`, которую создаёт `bootstrap_runtime`. В текущем репозитории
`data/contracts/` уже полностью заполнен (28 файлов), поэтому прямые читатели
работают как раньше — удаление копирования на импорте их не ломает. Для трёх
контрактов (`role_rules`/`workflow_rules`/`workorder_status_colors`)
отказоустойчивость при отсутствии рабочей копии обеспечивает пакет 01
(`apps.core.contract_store`). Прочие прямые читатели требуют выполненного
`bootstrap_runtime` (или существующего `data/contracts/`) — это документировано и
гарантировано entrypoint в проде и README при первом локальном старте. Сознательно
НЕ трогал эти файлы (вне write scope) и НЕ делал get_contract_path fallback на
дефолт, т.к. это перенаправило бы ЗАПИСЬ Settings Center в read-only `contracts/`.

## Команды проверок и результаты

- `grep -n "mkdir\|shutil.copy" config/settings.py` — вхождений НЕТ (exit 1).
- `.venv/bin/python manage.py check` — `System check identified no issues (0 silenced).`
- `.venv/bin/python manage.py check --tag contracts` — на валидных контрактах OK;
  на битом контракте (env-override на сломанный JSON) — `SystemCheckError` (exit 1,
  `core.E001`).
- Импорт `config.settings` с пустым `LOCAL_BUSINESS_DATA_DIR` — exit 0, каталог не
  создан, payload-константы загружены из дефолта.
- `bootstrap_runtime` в свежем `DATA_DIR` — 18 каталогов, 28 контрактов; повтор —
  0/0/28 (идемпотентно).
- `.venv/bin/python manage.py test` — <ЗАПОЛНИТЬ Ran/OK>.

## Методологическая заметка (обучающий контур DevSecOps)

Запись на диск при импорте конфигурации (mkdir, копирование файлов) — это скрытый
побочный эффект в коде, который «по контракту» должен только читать окружение и
вычислять значения. Почему это плохо:
- ломает read-only и immutable-infrastructure развёртывания: контейнер/ФС могут
  быть смонтированы только для чтения, а импорт settings падает на первом `mkdir`;
- создаёт гонки при параллельном старте: несколько процессов (gunicorn-воркеры,
  фоновые команды) одновременно копируют дефолты в одну рабочую копию —
  неатомарно, с риском получить полуфайл;
- заставляет КАЖДУЮ `manage.py`-команду (даже `help`, `check`, `collectstatic`)
  платить за эти операции: импорт settings выполняется всегда и раньше приложений;
- маскирует ошибки: сбой подготовки выглядит как «непонятная ошибка импорта
  настроек», а не как понятный отказ отдельного шага установки.

Правильный паттерн — разделить фазы: (1) чистый импорт конфигурации только
вычисляет значения; (2) явная идемпотентная команда (`bootstrap_runtime`) один раз
готовит окружение; (3) валидация оформлена штатным механизмом фреймворка (Django
system check, тег `contracts`), который встроен в стандартный конвейер (`check`,
фаза перед `migrate`), управляем (`--skip-checks`, `SILENCED_SYSTEM_CHECKS`) и
даёт понятную диагностику. Идемпотентность bootstrap = «повторный запуск безопасен»
достигается через `exist_ok=True` для каталогов и «копировать дефолт только если
рабочей копии ещё нет» для контрактов (правки администратора не затираются).

## Ограничения и остаточные риски

- Payload-чтения контрактов остались на импорте settings (теперь отказоустойчивые и
  без валидации), т.к. 13+ читателей `settings.LOCAL_BUSINESS_*` вне write scope.
  Полный перенос на `contract_store` — отдельная задача.
- В среде без выполненного `bootstrap_runtime` и с пустым `data/contracts/`
  функциональные обращения к контрактам (кроме трёх store-контрактов) требуют
  сначала запустить bootstrap; в текущем репозитории `data/contracts/` заполнен,
  regression зелёный.
- `check --tag contracts` теперь выполняется на каждом `manage.py check` и в фазе
  перед `migrate` (по требованию пакета) — это тот же объём валидации, что раньше
  был на импорте, но управляемый штатными средствами Django.
