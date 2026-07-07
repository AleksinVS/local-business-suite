# Приёмка: 04-iis-debug-contour-isolation

Дата: 2026-07-07.
Роли: исполнитель — субагент (Sonnet); независимая проверка — не требуется
(`independent_verification: false`, риск medium); code-review и приёмка —
агент-оркестратор.

## Вердикт

**Принят.** Реализация чистая, покрытие полное, замечаний к доработке нет.

## Что проверено

Исполнение (executor report + code-review оркестратором):

- **Флаг деплоя `LOCAL_BUSINESS_IIS_COMPAT_ENABLED` (default false).** `MIDDLEWARE`
  собирается функцией `build_middleware(iis_compat_enabled)` — `PathInfoDebugMiddleware`
  добавляется только при флаге. Вынос в функцию сделан ради тестируемости по
  значению флага (список собирается на импорте settings, `override_settings` его
  не пересобирает) — грамотно.
- **`debug_request`** (дамп окружения) регистрируется в `apps/core/urls.py`
  только при `settings.DEBUG AND settings.LOCAL_BUSINESS_IIS_COMPAT_ENABLED` →
  404 в обычной эксплуатации.
- **Лог перенесён с жёстко зашитого `C:\inetpub\portal\debug_path.log` + `open()`
  на штатный `logging`:** логгер `apps.core.iis_path_debug` →
  `RotatingFileHandler` в `DATA_DIR/logs/iis_path_debug.log` с `delay=True`.
  Middleware пишет на уровне INFO, логгер по умолчанию WARNING → в дефолте ничего
  не пишется и файл не создаётся; подробный лог включается уровнем логгера через
  `LOCAL_BUSINESS_IIS_PATH_DEBUG_LOG_LEVEL=INFO` (отдельно от флага деплоя).
  Убрано молчаливое `try/except Exception: pass`.
- **PATH_INFO-эвристика для IIS не менялась** (non-goal соблюдён); `FORCE_SCRIPT_NAME`
  не тронут.
- **Мусорный файл `C:\inetpub\portal\debug_path.log` (797 КБ) удалён** из корня
  рабочей копии; в git не отслеживался (подпадал под `*.log`).
- `.env.example` — закомментированные примеры обоих флагов; `docs/deployment/IIS_SSO.md` —
  что включать на IIS. `env_bool`/`TRUE_VALUES` подняты выше по `config/settings.py`
  (нужны для флага) — старое определение удалено, дублей нет.
- Scope соблюдён: изменены ровно файлы из `write_scope`; `apps/ai/`, `agent_runtime`
  (зона параллельного пакета 05) не тронуты.

## Acceptance-проверки

- `.venv/bin/python manage.py test apps.core.tests` → **Ran 71 tests, OK**
  (62 + 9 новых `IisCompatContourTests`).
- Широкий регресс (общий `MIDDLEWARE`/urls): `manage.py test apps.accounts.tests
  apps.workorders.tests apps.settings_center.tests apps.notifications.tests` →
  **Ran 99 tests, OK** (прогнан исполнителем, перепроверен оркестратором по логу).
- `ls 'C:\inetpub\portal\debug_path.log'` → файла нет.
- `.venv/bin/python manage.py check` → без ошибок.

## Покрытие тестами (9 новых)

Флаг off → middleware вне `MIDDLEWARE` и запрос не создаёт файлов; флаг on →
PATH_INFO-фикс работает и пропускает favicon/static; middleware пишет через
logging, а не `open()`; `debug_request` → 404 при флаге off и при DEBUG off даже
с флагом on, доступен при DEBUG+флаг.
