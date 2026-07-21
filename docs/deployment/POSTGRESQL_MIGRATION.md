# PostgreSQL Migration Runbook

## Назначение

Runbook описывает исполнительный порядок миграции основного репозитория с текущих SQLite runtime-файлов на одну PostgreSQL database.

Документ является целевым: часть команд `postgres_migration_*` должна быть реализована в workflow `workflow/active/postgresql-primary-store-migration/` до production cutover.

## Принципы

- PostgreSQL становится единственным production target основного репозитория.
- SQLite-вариант живет в отдельном fork/ветке.
- Cutover выполняется только после dry-run на копии runtime-данных.
- Временные export/import пакеты пишутся только в `.local/`.
- Runtime-файлы в `data/` не удаляются до подтвержденного backup и приемки.

## Предварительные условия

1. ADR-0029 принят.
2. SQLite baseline сохранен в ветке:

```bash
git branch --list sqlite-legacy-2026-06-15
```

3. Создан или согласован удаленный SQLite-fork.
4. PostgreSQL доступен из Django runtime.
5. Production traffic можно остановить на время freeze window.
6. Есть место для backup `data/` и export package.

## Backup перед миграцией

Пример локального backup в `.local/`:

```bash
mkdir -p .local/backups/postgresql-migration
tar -czf .local/backups/postgresql-migration/data-pre-postgres-$(date +%Y%m%d-%H%M%S).tar.gz data
git status --short > .local/backups/postgresql-migration/git-status-pre-postgres.txt
```

Для production backup дополнительно зафиксировать:

- snapshot VM/volume или host backup reference;
- backup PostgreSQL target, если cutover повторный;
- список SQLite-файлов и размер;
- commit hash основного репозитория;
- значение `DJANGO_ENV`, database env и deployment profile.

## PostgreSQL target

Минимальные требования:

- отдельная database для приложения;
- отдельный пользователь приложения с ограниченными правами;
- регулярный backup;
- WAL/PITR или другой согласованный механизм восстановления;
- расширения только по необходимости.

Целевые расширения первого среза:

```sql
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

`pgvector` добавлять только после отдельного решения по векторному backend.

## Переменные окружения

Целевой production profile должен задавать PostgreSQL явно, например:

```env
DJANGO_ENV=production
LOCAL_BUSINESS_DB_BACKEND=postgresql
DATABASE_URL=postgresql://local_business_app:<password>@<host>:5432/local_business_suite
LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND=postgresql
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND=database
```

SQLite в `DJANGO_ENV=production` основного репозитория должен быть запрещен, кроме аварийного override, согласованного владельцем. Это относится и к вспомогательным SQLite-бэкендам (`LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND=sqlite_fts`, `LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND=sqlite`).

## Dry-run порядок

Dry-run выполняется на копии runtime-данных, не на живом production.

1. Подготовить чистую PostgreSQL database.
2. Применить миграции:

```bash
python manage.py migrate --noinput
```

3. Экспортировать SQLite runtime package:

```bash
python manage.py postgres_migration_export \
  --output .local/postgresql-migration/export-package \
  --dry-run
```

4. Выполнить реальный export на копии:

```bash
python manage.py postgres_migration_export \
  --output .local/postgresql-migration/export-package
```

Export package включает только таблицы текущей Django-схемы и не переносит служебные таблицы
`django_migrations`, `django_content_type`, `auth_permission`, permission M2M, admin log и sessions.
Целевая PostgreSQL database должна сначала получить их через `python manage.py migrate`.
При пересечении таблиц в нескольких SQLite-файлах exporter выбирает доменный источник истины:
`chat.sqlite3` для `ai_*`, `knowledge_meta.sqlite3` для `memory_*`,
`analytics_control.sqlite3` для `analytics_*`, `main_vault.sqlite3` для остальных доменов.
Это предотвращает смешивание дочерних таблиц из специализированных SQLite-файлов с устаревшими
родительскими строками из `main_vault.sqlite3`.

5. Импортировать в PostgreSQL:

```bash
python manage.py postgres_migration_validate \
  --input .local/postgresql-migration/export-package \
  --package-only

python manage.py postgres_migration_import \
  --input .local/postgresql-migration/export-package \
  --dry-run

python manage.py postgres_migration_import \
  --input .local/postgresql-migration/export-package
```

6. Проверить целостность:

```bash
python manage.py postgres_migration_validate \
  --input .local/postgresql-migration/export-package \
  --strict
```

7. Перестроить search:

```bash
LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND=postgresql \
python manage.py memory_reindex --corpus all --backend fulltext
python manage.py source_adapter_reconcile --source-code workorders --target memory --backend fulltext
python manage.py memory_eval --dry-run
```

8. Выполнить smoke/e2e:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests apps.memory.tests apps.analytics.tests apps.workorders.tests
python manage.py memory_file_backed_e2e
python manage.py memory_file_content_search_e2e
```

## Production cutover

1. Объявить freeze window.
2. Остановить web и все workers.
3. Сделать backup `data/`.
4. Создать или очистить целевую PostgreSQL database.
5. Применить миграции.
6. Экспортировать SQLite runtime package.
7. Импортировать package в PostgreSQL.
8. Запустить strict validation.
9. Перестроить search indexes.
10. Обновить `.env.production` на PostgreSQL.
11. Запустить web и workers.
12. Выполнить smoke checks.
13. Открыть traffic.

## Smoke checks после cutover

Минимальный список:

- вход пользователя;
- открытие канбан-доски;
- создание тестовой заявки;
- переход статуса заявки и появление notification;
- открытие AI chat;
- запись `AgentActionLog`;
- `memory.search` по known test knowledge;
- `MemoryAccessAudit` создается;
- analytics control command запускается в dry-run;
- admin открывает основные модели без ошибок.

## Rollback

Rollback без сложной сверки допустим только до открытия traffic после cutover.

Порядок:

1. Остановить web и workers.
2. Вернуть предыдущий env с SQLite или переключиться на SQLite-fork deployment.
3. Восстановить `data/` из backup, если cutover менял runtime-файлы.
4. Запустить smoke checks старого контура.
5. Зафиксировать причину rollback и не удалять PostgreSQL database до разбора.

Если traffic уже был открыт и пользователи писали в PostgreSQL, rollback требует отдельной delta-reconciliation задачи. Нельзя просто переключиться обратно на старые SQLite-файлы без потери новых записей.

## Что нельзя делать

- Нельзя переносить текущие четыре SQLite-файла в четыре PostgreSQL database.
- Нельзя запускать cutover без backup `data/`.
- Нельзя писать export packages в корень проекта.
- Нельзя удалять SQLite-файлы до приемки PostgreSQL cutover.
- Нельзя включать RabbitMQ/Qdrant/OpenSearch в первый cutover без отдельного решения.

## Артефакты приемки

После успешной миграции сохранить в workflow-блоке:

- migration export manifest;
- validation report без секретов;
- список команд и статусов;
- smoke/e2e результаты;
- rollback window result;
- решение о закрытии SQLite runtime в `main`.
