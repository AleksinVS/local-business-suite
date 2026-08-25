# Миграция основного хранилища на PostgreSQL

Статус: production cutover выполнен 2026-08-18 и принят владельцем; active до
перевода backup Scheduled Task на отдельную identity и решения по архивному
SQLite runtime.

Связанные материалы:

- ADR: `docs/adr/ADR-0029-postgresql-primary-store-and-sqlite-fork.md`;
- проектный план: `docs/architecture/POSTGRESQL_PRIMARY_STORE_PLAN.md`;
- runbook: `docs/deployment/POSTGRESQL_MIGRATION.md`;
- workflow-блок: `workflow/active/postgresql-primary-store-migration/`.

## Цель

Подготовить и выполнить переход основного репозитория с SQLite-разделения на одну PostgreSQL database перед продуктовым релизом.

Главная ценность: получить production-готовое транзакционное хранилище с физическими внешними ключами, нормальными row locks, backup/restore, едиными миграциями и понятным cutover.

## Scope

1. SQLite fork:
   - сохранить текущий SQLite-вариант как отдельную ветку/форк;
   - документировать ограничения SQLite-fork;
   - прекратить развитие SQLite как production-направления в `main`.

2. PostgreSQL settings and deployment:
   - добавить PostgreSQL-зависимости и настройки;
   - обновить Docker/IIS deployment;
   - запретить SQLite в production основного репозитория без явного override.

3. Single database model:
   - перейти на один `default` alias;
   - убрать постоянную маршрутизацию `chat`, `knowledge_meta`, `analytics_control`;
   - вернуть физические FK там, где связи внутренние и обязательные.

4. Migration tooling:
   - экспортировать runtime-данные из текущих SQLite-файлов;
   - импортировать их в PostgreSQL;
   - валидировать counts, orphan rows, FK, audit continuity и search readiness.

5. Search, queues and workers:
   - заменить SQLite FTS production-путь на PostgreSQL FTS;
   - перевести SQLite queue files на PostgreSQL job/outbox tables или явно ограничить workers до отдельного broker-решения;
   - отложить pgvector/Qdrant/RabbitMQ/Celery до отдельных решений, если они не нужны для первого cutover.

6. Cutover and rollback:
   - описать freeze window;
   - подготовить backup;
   - выполнить dry-run;
   - провести production cutover;
   - иметь rollback до открытия traffic.

## Non-goals

- Не внедрять четыре PostgreSQL database вместо четырех SQLite-файлов.
- Не переносить `data/knowledge_repo/`, `data/contracts/` и media в PostgreSQL.
- Не внедрять Qdrant/OpenSearch/RabbitMQ/Celery в первом срезе без отдельного ADR.
- Не поддерживать SQLite как равноправный production backend в основном репозитории.
- Не удалять текущие SQLite runtime-файлы без backup и явного cutover.

## Write Scope

Ожидаемый write scope реализации:

- `config/settings.py`;
- `requirements.txt`, `requirements.lock`;
- `docker-compose.yml`, `Dockerfile`, `docker/entrypoint.prod.sh`;
- возможно новый `docker-compose.postgres.yml` или compose profile;
- `apps/core/db_routers.py`;
- модели и миграции `apps/ai`, `apps/memory`, `apps/analytics`, `apps/*`;
- новые management commands для export/import/validate;
- search backend в `apps/memory`;
- queue backend в `apps/memory` и analytics jobs;
- tests in `apps/*/tests.py`;
- `docs/deployment/`, `docs/guides/`, `README.md`;
- `.desc.json`, `PROJECT_STRUCTURE.yaml`.

## Acceptance Checks

Минимальные проверки после реализации:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test apps.core.tests apps.accounts.tests apps.inventory.tests apps.workorders.tests apps.notifications.tests apps.ai.tests apps.memory.tests apps.analytics.tests apps.settings_center.tests
python manage.py memory_file_backed_e2e
python manage.py memory_file_content_search_e2e
python manage.py memory_eval --dry-run
git diff --check
```

Migration-specific checks:

```bash
python manage.py postgres_migration_export --dry-run
python manage.py postgres_migration_import --dry-run
python manage.py postgres_migration_validate --strict
python manage.py memory_reindex --corpus all --backend fulltext
```

Команды `postgres_migration_*` реализованы; этот список остаётся обязательной
матрицей при переносе или восстановлении следующего хоста.

## ADR

ADR обязателен и уже создан: `docs/adr/ADR-0029-postgresql-primary-store-and-sqlite-fork.md`.

Дополнительный ADR нужен, если в первом срезе будет решено:

- внедрять RabbitMQ/Celery как production broker;
- внедрять Qdrant/OpenSearch/Meilisearch;
- менять модель хранения файлов знаний;
- менять security/privacy модель migration export packages.

## Порядок Работ

1. Выполнено: baseline SQLite опубликован в `origin/sqlite-legacy-2026-06-15`.
2. Выполнено: PostgreSQL-инфраструктура, единая schema и migration tooling.
3. Выполнено: search/queue переведены на PostgreSQL и database backend.
4. Выполнено: два dry-run, production cutover и e2e/smoke-приёмка.
5. Обязательно после security-review: отключить старую SYSTEM backup task и
   пересоздать её под отдельной backup identity по deployment-runbook.
6. Решить судьбу legacy SQLite runtime в `main`, затем архивировать блок.

## Остаточные Риски

- Standalone SQLite-репозиторий не создан; baseline-ветка опубликована на remote.
- Rollback window закрыт после записи production-данных; возврат требует
  отдельной сверки новых PostgreSQL-записей.
- Старая SYSTEM backup task небезопасна и должна оставаться отключённой до
  перевода на dedicated identity и закрытый `ProgramData` backup root.
- Search ranking изменится после перехода с SQLite FTS на PostgreSQL FTS.
- SQLite-fork может отстать от security fixes, если не будет явной политики cherry-pick.
