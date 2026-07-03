# PostgreSQL Primary Store Migration Plan

## Назначение

Документ описывает целевую архитектуру перехода основного репозитория с SQLite-разделения на одну PostgreSQL database. Он дополняет ADR-0029 и является проектной основой для active plan и workflow-пакета.

## Цель

Сделать PostgreSQL основным транзакционным хранилищем проекта перед продуктовым релизом, сохранив SQLite-вариант в отдельном fork/ветке для legacy, демо и малых локальных установок.

## Текущая проблема

Сейчас runtime-состояние Django физически разделено:

```text
data/db/main_vault.sqlite3
data/db/chat.sqlite3
data/db/knowledge_meta.sqlite3
data/db/analytics_control.sqlite3
data/indexes/fulltext/search.sqlite3
data/queues/*.sqlite3
```

Это помогло отделить домены на этапе MVP, но создало системные ограничения:

- междоменные связи стали логическими, а не физическими;
- `db_constraint=False` стал частью рабочей модели для пользователей, чатов, памяти и аналитики;
- миграции нескольких alias легко расходятся с реальным production entrypoint;
- конкурирующая запись AI-чата, уведомлений, audit, ingestion и workers упирается в SQLite locking;
- backup/restore одного продукта превращается в согласование нескольких файлов, индексов и очередей.

## Целевая модель

Основной репозиторий:

```text
PostgreSQL database: local_business_suite
  Django auth/session/contenttypes
  accounts/core/settings_center
  inventory/workorders/waiting_list/notifications
  ai chat, action logs, pending actions
  memory metadata, review, audit, ingestion, job metadata
  analytics control models
```

Файловые runtime-слои остаются вне PostgreSQL:

```text
data/contracts/          # runtime-копии контрактов
data/knowledge_repo/     # принятые знания и Git history
data/media/              # вложения
data/processing/         # временная обработка
data/analytics/duckdb/   # аналитические витрины
```

## Что заменить

| Текущий элемент | Целевое состояние |
| --- | --- |
| `main_vault.sqlite3`, `chat.sqlite3`, `knowledge_meta.sqlite3`, `analytics_control.sqlite3` | Одна PostgreSQL database |
| `LocalBusinessDatabaseRouter` как постоянная маршрутизация доменов | Удалить или оставить только для legacy migration/import commands |
| `db_constraint=False` для внутренних связей | Вернуть обычные FK там, где связь должна быть строгой |
| SQLite FTS индекс | `MemoryFullTextIndex` в PostgreSQL с `to_tsvector`/GIN; SQLite FTS только dev/legacy |
| SQLite queue files | `MemoryExternalConnectorJob` в PostgreSQL; broker позже отдельным ADR |
| SQLite production deployment | Отдельный SQLite fork; в `main` production target PostgreSQL |

## Что не заменять

- `data/knowledge_repo/` не переносить в БД: файлы знаний остаются источником текста принятого знания.
- `data/contracts/` не переносить в БД: runtime contracts остаются файлами с атомарной записью.
- `data/media/` не переносить в БД: PostgreSQL хранит метаданные, путь, хэш и audit.
- DuckDB не заменять PostgreSQL для тяжелых аналитических витрин.

## Архитектурные слои

### Django OLTP

PostgreSQL является единственным production-хранилищем реляционных моделей Django.

Обязательные свойства:

- один `default` alias;
- единые миграции;
- физические внешние ключи;
- `select_for_update` и row locks для pending actions, job leasing и критичных write paths;
- production backup/restore и healthcheck.

### Поиск

Первый целевой search backend:

- PostgreSQL FTS для знания и source-data search documents через `MemoryFullTextIndex`;
- условный `GIN` index `memory_fulltext_search_text_gin` в PostgreSQL migration;
- `pg_trgm` для похожих строк, если это нужно после замеров;
- отдельный интерфейс search backend в коде, чтобы SQLite-fork мог сохранить свою реализацию.

OpenSearch/Meilisearch/Elasticsearch не включаются в первый срез.

### Очереди

Первый целевой queue backend:

- PostgreSQL job/outbox table `MemoryExternalConnectorJob`;
- `status`, `locked_by`, `locked_until`, `attempt_count`, `next_attempt_at`, `idempotency_key`;
- `select_for_update(skip_locked=True)` для конкурентного leasing;
- отдельные команды cleanup/retry.

RabbitMQ/Celery выбираются после появления реального production scheduler и нагрузки.

### Векторы

Векторный поиск отделен от базовой миграции.

Допустимые варианты после первого среза:

- `pgvector` как минимальный production-компонент;
- Qdrant как отдельная СУБД для высокой нагрузки и сложных payload-фильтров;
- LanceDB только как локальный experimental/dev backend.

## SQLite-fork

Локальная ветка-указатель создана:

```bash
git branch sqlite-legacy-2026-06-15
```

Целевой порядок выноса:

1. Создать отдельный удаленный репозиторий или fork, например `local-business-suite-sqlite`.
2. Запушить туда ветку `sqlite-legacy-2026-06-15` как `main` или `sqlite-main`.
3. В SQLite-fork README указать ограничения: small-install, single-host, без production-гарантий для конкурирующих writers и тяжелого ingestion.
4. В основном репозитории после начала миграции не принимать новые SQLite-first изменения.
5. Security fixes переносить вручную cherry-pick только при совместимости.

## Этапы миграции

### Этап 0. Подготовка fork

- Зафиксировать SQLite baseline.
- Создать удаленный fork.
- Добавить в fork предупреждения и режим поддержки.
- Убедиться, что основной `main` не зависит от дальнейших SQLite-решений.

### Этап 1. PostgreSQL infrastructure

- Добавить PostgreSQL-зависимость Python.
- Добавить env-настройки `DATABASE_URL` или явные `POSTGRES_*`.
- Обновить Docker Compose и deployment profile.
- Добавить healthcheck PostgreSQL.
- Остановить использование нескольких alias в обычном runtime.

### Этап 2. Single database schema

- Перевести все Django models на `default`.
- Убрать или ограничить `LocalBusinessDatabaseRouter`.
- Вернуть физические FK для внутренних связей.
- Проверить миграции на пустой PostgreSQL database.

### Этап 3. Data migration tooling

- Создать management commands:
  - export из текущих SQLite-файлов в manifest-пакет;
  - import в PostgreSQL;
  - validate counts, FK, orphan rows, audit continuity;
  - optional dry-run report.
- Писать временные пакеты только в `.local/`.

### Этап 4. Search and queue backend

- Перенести search documents в PostgreSQL: реализован первый `MemoryFullTextIndex`, требуется dry-run rebuild на копии данных.
- Реализовать PostgreSQL FTS backend: реализован `LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND=postgresql`.
- Заменить SQLite queue files на PostgreSQL job/outbox tables: реализован `LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND=database`.
- Добавить rebuild commands для search/vector indexes.

### Этап 5. Cutover

- Остановить writers.
- Сделать backup SQLite, media, contracts, knowledge repo.
- Выполнить export/import.
- Применить миграции PostgreSQL.
- Перестроить search indexes.
- Прогнать smoke/e2e.
- Включить production traffic.

### Этап 6. Cleanup

- Удалить legacy multi-db настройки из `main`.
- Удалить устаревшие SQLite deployment инструкции из основного репозитория.
- Обновить README, deployment docs, testing policy, PROJECT_STRUCTURE.
- Архивировать workflow после приемки.

## Acceptance

Проект готов к реализации, когда:

- ADR-0029 принят;
- SQLite-fork baseline создан;
- active plan и workflow package есть;
- runbook миграции описывает backup, import, validation, cutover и rollback.

Реализация считается завершенной, когда:

- `DJANGO_ENV=production` использует PostgreSQL;
- все основные модели Django живут в одной PostgreSQL database;
- внутренние FK восстановлены там, где они обязательны;
- AI chat, workorders, notifications, memory audit, ingestion metadata и analytics control проходят unit/integration tests;
- search работает через PostgreSQL FTS или явно отключен до rebuild;
- migration dry-run выполнен на копии runtime-данных;
- e2e проверяет основной пользовательский сценарий после cutover;
- SQLite-fork отделен и documented.

## Проверки

Минимум для PostgreSQL-среза:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test apps.core.tests apps.accounts.tests apps.inventory.tests apps.workorders.tests apps.notifications.tests apps.ai.tests apps.memory.tests apps.analytics.tests apps.settings_center.tests
python manage.py memory_file_backed_e2e
python manage.py memory_file_content_search_e2e
git diff --check
```

Перед cutover дополнительно:

```bash
python manage.py postgres_migration_export --dry-run
python manage.py postgres_migration_import --dry-run
python manage.py postgres_migration_validate --strict
python manage.py memory_reindex --corpus all --backend fulltext
python manage.py memory_eval --dry-run
```

Команды migration tooling будут добавлены в реализационных задачах.

## Риски

| Риск | Митигация |
| --- | --- |
| Потеря данных при переносе из четырех SQLite-файлов | Export manifest, checksums, row counts, FK validation, read-only freeze на время cutover |
| Несовместимость миграций SQLite/PostgreSQL | PostgreSQL-first миграции, отдельный SQLite-fork, dry-run на копии |
| Search results изменятся | Отдельная приемка `memory.search`, eval набор и документированный rebuild |
| Очереди потеряют jobs | Перенос через job manifest, idempotency keys и сверка статусов |
| Rollback после новых записей в PostgreSQL сложен | Freeze window, rollback только до открытия traffic или отдельная delta-reconciliation задача |
