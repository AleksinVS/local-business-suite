# Executor Report: PostgreSQL Dev Cutover Verification

Дата: 2026-07-04

## Контекст

Кодовый срез миграции (ADR-0029) был принят ранее как готовый к dry-run
(`EXECUTOR_REPORT.postgresql-code-slice.md`). На момент этого отчета production
и реальных runtime-данных нет — проект на ранней стадии разработки. Поэтому
«cutover с freeze window на реальных данных» неприменим; вместо него выполнена
и проверена работоспособность основного репозитория на реальном PostgreSQL в
dev-среде.

## Выполнено

- Поднят реальный PostgreSQL 17 в контейнере (`lbs-pg-verify`, порт 5432).
- `python manage.py migrate` на PostgreSQL — вся схема (14 приложений) строится
  чисто, `showmigrations` показывает 0 неприменённых миграций.
- `python manage.py check` и `validate_architecture_contracts` — без замечаний.
- Полный приёмочный набор тестов по пакету 06 пройден на PostgreSQL:
  - `apps.memory.tests`, `apps.ai.tests` — зелёные (exit 0);
  - `apps.core/accounts/inventory/workorders/notifications/analytics/settings_center`
    — 146 тестов, OK.
- e2e на PostgreSQL: `memory_file_backed_e2e` — успех; `memory_eval --dry-run`
  — passed=6, failed=0; `memory_file_content_search_e2e` — успех (после
  исправления, см. ниже).
- Инструменты миграции отработали end-to-end (export/validate/import артефакты
  в `.local/postgresql-migration/`).
- SQLite baseline-ветка `sqlite-legacy-2026-06-15` выложена на origin как
  линия SQLite-варианта.

## Исправленный дефект (PostgreSQL-specific)

`memory_file_content_search_e2e` падал только на PostgreSQL
(«Prefix fallback was not reflected in retrieval trace»), на SQLite проходил.

Причина: SQLite FTS-бэкенд выполняет prefix-fallback и помечает документы
флагом `prefix_search_used` в retrieval-trace, а `PostgreSQLFullTextMemoryBackend`
делал только plain `tsquery` — префиксный запрос не находил документ и флаг не
выставлялся.

Исправление (`apps/memory/vector_backends.py`, commit `f68f399`): при недоборе
до лимита `_search_postgresql` выполняет raw prefix `tsquery` (`term:*`),
объединяет строки с дедупликацией и помечает префиксные документы
`prefix_search_used` / `*_prefix` в `fulltext_mode`. Проверено: e2e проходит на
обоих бэкендах, регрессий в `apps.memory`/`apps.ai` нет.

## Не выполнено (обоснованно)

- Production cutover с freeze window — production ещё не существует; при его
  появлении выполняется по runbook `docs/deployment/POSTGRESQL_MIGRATION.md`.
- Dry-run на копии реальных runtime SQLite-файлов — реальных данных нет.
- Отдельный standalone SQLite-fork как самостоятельный репозиторий — при
  необходимости создаётся владельцем из ветки `origin/sqlite-legacy-2026-06-15`.

## Проверки

```bash
LOCAL_BUSINESS_DB_BACKEND=postgresql POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 \
POSTGRES_DB=local_business_suite POSTGRES_USER=local_business_app \
POSTGRES_PASSWORD=<dev> python manage.py migrate
... check / validate_architecture_contracts / test <apps> / memory_*_e2e / memory_eval --dry-run
```

Результат: основной репозиторий работает на PostgreSQL end-to-end в dev.
Блок `memory-hybrid-knowledge-v05-alignment` (ADR-0030) разблокирован.
