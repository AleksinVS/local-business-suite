# Приёмка: 07-settings-bootstrap-extraction

Дата: 2026-07-07.
Роли: исполнитель — субагент (Opus); независимая проверка — не требуется
(`independent_verification: false`); code-review и приёмка — агент-оркестратор.

## Вердикт

**Принят.** Крупный рефактор `config/settings.py` выполнен чисто, побочки убраны,
fail-fast сохранён, полный регресс зелёный.

## Что проверено (code-review оркестратором)

- **Импорт settings без побочек:** удалён цикл `mkdir` (~15 каталогов) и
  `os.makedirs` для contracts; `get_contract_path` — чистое вычисление пути (без
  `mkdir`/`shutil.copy`, семантика env-override сохранена). `grep mkdir|shutil.copy
  config/settings.py` → пусто.
- **`_load_contract_payload`:** payload-константы читаются устойчиво (рабочая копия
  → упакованный дефолт → `None`), без валидации и без падения импорта. Т.к.
  дефолты в `contracts/` (git) всегда присутствуют и валидны, константы
  наполняются даже без выполненного bootstrap — регрессии для читателей нет.
- **Валидация перенесена, не удалена:** новый `apps/core/checks.py` —
  `@register("contracts")` system check, инстанцирует команду
  `validate_architecture_contracts` и зовёт `handle()` напрямую (не `execute()`
  → нет рекурсии «check → команда → check»), вывод в StringIO (без шума на
  `manage.py check`), битый контракт → `Error core.E001`. Fail-fast сохранён:
  проверку выполняют `manage.py check` (его зовёт `make check`),
  `check --tag contracts` и system-check-фаза перед `migrate`.
- **`bootstrap_runtime` (новая команда):** идемпотентная (каталоги `exist_ok`;
  контракт копируется только если рабочей копии нет — правки Settings Center не
  затираются); пропуск `schemas/`/`.desc.json`; `--dry-run`;
  `requires_system_checks=()` (не блокируется contracts-проверкой до копирования).
  Строит пути от `settings.DATA_DIR`.
- **`entrypoint.prod.sh`:** `python manage.py bootstrap_runtime` перед
  `wait_for_database`/`migrate` (не требует БД, не гоняет checks); прежний
  жёсткий `mkdir -p /app/data/...` заменён (staticfiles-mkdir оставлен).
- **Флаги → `env_bool`:** оставшиеся ручные разборы булевых флагов
  (`DJANGO_SECURE_SSL_REDIRECT`, `*_COOKIE_SECURE`, `COPILOTKIT_ENABLED`,
  `SETTINGS_CENTER_*`, `ACCOUNTS_AD_*`, `MEMORY_ACL_*` и др.) переведены на
  `env_bool` (заодно `=1` теперь работает наравне с `=True`).
- **`LOCAL_BUSINESS_DATA_DIR` override** для `DATA_DIR` — расположение по умолчанию
  не изменено (`BASE_DIR/data`), override нужен для теста чистого импорта.
- Scope соблюдён; `apps/core/.desc.json` + PROJECT_STRUCTURE.yaml обновлены.

## Acceptance-проверки

- `.venv/bin/python manage.py test` (**полный набор**) → **Ran 432 tests, OK**.
- `.venv/bin/python manage.py check` → без ошибок; `check --tag contracts` →
  проходит на валидных, поднимает `SystemCheckError` на битом контракте.
- `grep -n "mkdir\|shutil.copy" config/settings.py` → вхождений нет.
- Импорт `config.settings` в подпроцессе с `LOCAL_BUSINESS_DATA_DIR` на
  несуществующий каталог → ничего не создаётся, не падает (тест
  `SettingsImportSideEffectTests`).
- `bootstrap_runtime` в чистом `DATA_DIR` → 18 каталогов + 28 контрактов,
  повторный запуск идемпотентен (тест `BootstrapRuntimeCommandTests`).

## Примечание по исполнению

Агент упёрся в лимит сессии на финальном шаге (полный регресс ещё шёл); прогон
завершился успешно (`Ran 432, OK`), оркестратор снял результат из лога и
оформил приёмку. Реализация к моменту лимита была полной и в scope.

## Замечание (в рекомендацию)

`_load_contract_payload` может вернуть `None`, если отсутствуют И рабочая копия,
И упакованный дефолт (в валидном чекауте не возникает). Читатели через
`getattr(settings, "...", default)` устойчивы; прямые подписчики защищены тем,
что дефолты всегда на месте. Долгосрочно чтение контрактов стоит вести через
`contract_store` (ADR-0031) — отдельный управляемый долг.
