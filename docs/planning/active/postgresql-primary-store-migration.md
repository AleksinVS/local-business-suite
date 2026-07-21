# Миграция основного хранилища на PostgreSQL

Статус: active plan; кодовый срез миграции реализован, внешний dry-run/cutover еще не выполнен.

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

Команды `postgres_migration_*` должны быть добавлены в процессе реализации.

## ADR

ADR обязателен и уже создан: `docs/adr/ADR-0029-postgresql-primary-store-and-sqlite-fork.md`.

Дополнительный ADR нужен, если в первом срезе будет решено:

- внедрять RabbitMQ/Celery как production broker;
- внедрять Qdrant/OpenSearch/Meilisearch;
- менять модель хранения файлов знаний;
- менять security/privacy модель migration export packages.

## Порядок Работ

1. Завершить вынос SQLite-варианта в удаленный fork.
2. Добавить PostgreSQL-инфраструктуру и настройки.
3. Перевести проект на одну database schema.
4. Добавить export/import/validate tooling.
5. Перевести search и очереди на PostgreSQL-путь.
6. Выполнить dry-run на копии runtime-данных.
7. Провести cutover и e2e.
8. Удалить legacy multi-db runtime из `main`.

## Остаточные Риски

- Удаленный SQLite-fork еще не создан владельцем репозитория; локальная ветка `sqlite-legacy-2026-06-15` уже подготовлена.
- Export/import tooling проверен локально и требует dry-run на копии реальных runtime SQLite-файлов перед production cutover.
- PostgreSQL cutover может потребовать downtime, если нет online sync.
- Rollback после открытия traffic потребует отдельной сверки новых PostgreSQL-записей.
- Search ranking изменится после перехода с SQLite FTS на PostgreSQL FTS.
- SQLite-fork может отстать от security fixes, если не будет явной политики cherry-pick.
