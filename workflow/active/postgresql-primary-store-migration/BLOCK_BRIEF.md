# Миграция основного хранилища на PostgreSQL

## Цель

Перевести основной репозиторий с текущего SQLite-разделения на одну PostgreSQL database и вынести SQLite-вариант в отдельный fork/ветку.

## Бизнес-ценность

Перед продуктовым релизом проект получает production-готовое хранение данных: физические внешние ключи, row locks, нормальный backup/restore, единые миграции и устойчивость к нескольким web/worker процессам.

## Write Scope

Предполагаемый write scope реализации:

- `config/settings.py`;
- `requirements.txt`, `requirements.lock`;
- `docker-compose.yml`, `Dockerfile`, `docker/entrypoint.prod.sh`;
- deployment scripts and docs;
- `apps/core/db_routers.py`;
- Django models/migrations in `apps/ai`, `apps/memory`, `apps/analytics`, `apps/*`;
- management commands for migration export/import/validate;
- memory search backend and queue backend;
- tests in touched apps;
- documentation, `.desc.json`, `PROJECT_STRUCTURE.yaml`.

## Non-goals

- Не переносить SQLite-разделение в четыре PostgreSQL database.
- Не внедрять RabbitMQ/Celery, Qdrant или OpenSearch в первом срезе без отдельного ADR.
- Не переносить файлы знаний, runtime contracts и media в PostgreSQL.
- Не удалять SQLite runtime-файлы до backup и приемки cutover.

## Acceptance

Работа считается принятой, когда:

- SQLite baseline вынесен в отдельный fork/ветку и documented;
- основной production target использует одну PostgreSQL database;
- много-базовая маршрутизация больше не является обычным runtime путем;
- внутренние FK восстановлены там, где это обязательно;
- migration tooling экспортирует, импортирует и валидирует runtime-данные;
- PostgreSQL FTS или временный search fallback задокументирован и проверен;
- dry-run выполнен на копии данных;
- cutover runbook выполнен;
- unit/integration/e2e проверки пройдены или риски зафиксированы.
