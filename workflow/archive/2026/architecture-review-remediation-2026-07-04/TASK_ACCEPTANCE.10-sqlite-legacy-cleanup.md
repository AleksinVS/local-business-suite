# Приёмка: 10-sqlite-legacy-cleanup

Дата: 2026-07-07.
Роли: исполнитель — субагент (Sonnet); независимая проверка — не требуется
(`independent_verification: false`, риск low); code-review и приёмка —
агент-оркестратор.

## Вердикт

**Принят.** Чистка корректна, семантика миграционных путей сохранена 1:1,
полный регресс зелёный.

## Что проверено (code-review оркестратором)

- **Удалён `apps/core/db_routers.py`** — no-op `LocalBusinessDatabaseRouter`, нигде
  не подключён.
- **`config/settings.py`:** убраны `DATABASE_ROUTERS = []` (заменён поясняющим
  комментарием: единственная база `default` по ADR-0029, не забытая настройка),
  словарь `LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES` и мёртвая константа
  `LOCAL_BUSINESS_DB_SPLIT_ENABLED = False`.
- **Словарь legacy-путей перенесён в `apps/core/postgresql_migration.py`:**
  `legacy_sqlite_databases()` строит его напрямую из env
  (`LOCAL_BUSINESS_LEGACY_SQLITE_*_PATH`, те же дефолты под `settings.DATA_DIR`) —
  семантика 1:1, без чтения `settings`. Это конфиг инструмента миграции, ему не
  место в глобальных Django-настройках.
- **Потребители обновлены (авторизованное расширение scope):**
  `apps/ai/management/commands/migrate_legacy_chat_db.py` и
  `apps/analytics/management/commands/migrate_legacy_analytics_control_db.py`
  теперь берут пути из `apps.core.postgresql_migration.legacy_sqlite_databases()`,
  а не из `settings`. Перенос не вышел за этот список файлов.
- **Тесты `apps/core/tests.py`** (3 шт., использовавшие
  `override_settings(LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES=...)`) переведены на
  `patch("apps.core.postgresql_migration.legacy_sqlite_databases", ...)`.
- `apps/core/.desc.json`: убрана запись `db_routers.py`, уточнено описание
  `postgresql_migration.py`. `POSTGRESQL_MIGRATION.md` правок не потребовал.
- Non-goals соблюдены: команды export/import/validate и dev-режим
  `LOCAL_BUSINESS_DB_BACKEND=sqlite` не тронуты.

## Acceptance-проверки

- `grep -rn "DB_SPLIT_ENABLED|db_routers|LocalBusinessDatabaseRouter|
  LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES" apps/ config/ services/` → 0 вхождений.
- `.venv/bin/python manage.py test` (полный набор, исполнитель) → **Ran 432, OK**;
  оркестратор дополнительно перепрогнал `apps.core.tests apps.ai.tests
  apps.analytics` — зелено.
- `.venv/bin/python manage.py check` → без ошибок.
- Миграции: на чистой sqlite-базе `migrate` применяется полностью (exit 0),
  повторный `migrate --check` проходит.

## Примечание (pre-existing, вне пакета)

`migrate --check` на ТЕКУЩЕЙ dev-базе разработчика возвращает 1: 5 неприменённых
миграций (`core.0006_department_oid`, `inventory.0006-0009`) из слияния ветки
inventory (коммит `e1951a8`, до этой сессии) — состояние локальной dev-БД, не
дефект пакета 10 и не блокер (на чистой БД миграции проходят). Достаточно
`manage.py migrate` в dev-окружении, чтобы подтянуть их.
