# ADR-0029: PostgreSQL как основное хранилище и вынос SQLite-варианта

## Статус

Accepted

## Дата

2026-06-15

## Контекст

Проект начинался как local-first Django monorepo с SQLite. Это было полезно для быстрого MVP, локального запуска и первых пилотов без отдельного администратора СУБД.

Текущее состояние усложнилось:

- основное состояние разнесено по четырем SQLite-файлам: `main_vault`, `chat`, `knowledge_meta`, `analytics_control`;
- `apps.core.db_routers.LocalBusinessDatabaseRouter` маршрутизирует приложения по разным database alias;
- связи из `ai`, `memory` и `analytics` к пользователям и чатам частично стали логическими через `db_constraint=False`;
- появились AI chat, audit, ingestion, фоновые workers, очереди, файловая память, будущий аналитический контур и требования к production backup/restore;
- production-контур уже использует несколько web workers, что повышает риск блокировок записи SQLite.

Дальнейшее развитие в основном репозитории должно идти от production-целевой архитектуры, а не от удобства локального SQLite-MVP.

## Решение

Основной репозиторий переводится на целевую модель: **одна PostgreSQL database как основное транзакционное хранилище Django**.

SQLite-вариант выносится в отдельный совместимый fork/ветку для legacy, демо и малых локальных установок. В текущем рабочем дереве создана локальная ветка-указатель:

```text
sqlite-legacy-2026-06-15
```

Эта ветка фиксирует исходную точку текущего SQLite-состояния до начала PostgreSQL-миграции в `main`. Удаленный fork создается отдельным репозиторным действием владельца или сопровождающего, после чего ветка переносится туда как основная линия SQLite-варианта.

### Правила основного репозитория

В `main` целевой runtime:

```text
Django apps -> одна PostgreSQL database
```

Не переносить текущие четыре SQLite-файла в четыре PostgreSQL-базы. Это сохранило бы главную проблему: межбазовые связи, отсутствие физических внешних ключей и сложность транзакционной целостности.

Целевое размещение:

```text
PostgreSQL database
  accounts, auth, contenttypes, sessions
  core, settings_center
  inventory, workorders, waiting_list, notifications
  ai chat/action/session models
  memory metadata, audit, ingestion/review/job metadata
  analytics control models

data/knowledge_repo/
  принятые знания как файлы и Git history

data/media/
  пользовательские вложения и медиа

data/contracts/
  runtime-контракты

data/analytics/duckdb/
  аналитические витрины и тяжелые OLAP-срезы
```

### Поиск

Первый production-вариант поиска строится на PostgreSQL:

- PostgreSQL full-text search для `knowledge` и `source_data` search documents через `MemoryFullTextIndex`;
- `GIN` indexes для полнотекстового поиска;
- `pg_trgm` для нечеткого поиска и похожих строк, если потребуется;
- `unaccent` для нормализации текста, если это улучшит русскоязычный поиск.

SQLite FTS остается частью SQLite-fork и может использоваться как dev/legacy fallback, но не является целевым production-поиском основного репозитория.

### Векторы

Векторный поиск не должен блокировать первую миграцию основной БД.

Предпочтительный порядок:

1. Перевести транзакционные данные и FTS на PostgreSQL.
2. Затем выбрать векторный backend отдельным решением:
   - `pgvector`, если нужен минимальный набор production-компонентов;
   - Qdrant или другой отдельный vector DB, если появятся большие корпуса, сложные фильтры и высокая нагрузка;
   - LanceDB оставить как локальный dev/experimental backend, если он не является источником истины.

### Очереди и фоновые задачи

Для первого PostgreSQL-среза допустимы PostgreSQL job/outbox tables:

- `MemoryExternalConnectorJob` для очереди внешних коннекторов;
- `SELECT ... FOR UPDATE SKIP LOCKED` для leasing;
- idempotency keys;
- retry metadata;
- audit trail;
- явное ограничение числа workers.

RabbitMQ/Celery или другой broker выбирается отдельным ADR, когда появится production scheduler, много внешних источников или требования к независимой доставке сообщений.

### Аналитика

DuckDB остается допустимым аналитическим хранилищем для витрин, срезов и тяжелых агрегатов. Оно не заменяет основную PostgreSQL database.

### SQLite-fork

SQLite-вариант получает отдельную линию сопровождения:

- не является источником архитектурной истины для `main`;
- не блокирует использование PostgreSQL-возможностей в основном репозитории;
- может принимать security fixes и небольшие совместимые исправления;
- должен иметь собственные предупреждения о single-host/small-install ограничениях;
- не должен обещать production-гарантии для конкурирующей записи, фоновых workers, тяжелого ingestion и AI audit под нагрузкой.

## Альтернативы

### Сохранить SQLite в основном репозитории как равноправный production backend

Отклонено. Это сохранит блокировки записи, слабые гарантии для фоновых задач и постоянную необходимость ограничивать архитектуру под наименьший общий знаменатель.

### Перенести четыре SQLite-файла в четыре PostgreSQL database

Отклонено. Это технически похоже на текущую проблему: Django не получает полноценные внешние ключи и транзакции между доменами. Логическое разделение должно оставаться в приложениях и сервисах, а не в четырех независимых БД.

### Сразу внедрить PostgreSQL, RabbitMQ, Redis, Qdrant и OpenSearch

Отклонено для первого релиза. Это резко увеличит операционную сложность. Первый целевой шаг: одна PostgreSQL database, PostgreSQL FTS и понятный путь миграции данных.

### Оставить SQLite FTS как production search index рядом с PostgreSQL

Отклонено как основной путь. Такой вариант сохраняет отдельный файл с собственным lifecycle, backup и блокировками. Допустим только как временный rollback/dev fallback или в SQLite-fork.

## Последствия

Положительные:

- возвращаются физические FK и транзакционная целостность между пользователями, чатами, памятью, аналитикой и audit;
- упрощается модель миграций: один основной `default` database alias;
- production получает нормальные row locks, backup/restore, WAL/PITR, мониторинг и роли доступа;
- поиск и очереди можно развивать поверх одной согласованной СУБД;
- основной репозиторий перестает ограничиваться SQLite-гарантиями.

Отрицательные:

- локальный запуск станет тяжелее: нужен PostgreSQL или compose-профиль;
- потребуется миграция данных из четырех SQLite-файлов в одну PostgreSQL database;
- часть миграций, тестов и deployment-документов нужно переписать;
- SQLite-fork потребует отдельной политики сопровождения;
- rollback после cutover сложнее, если пользователи уже писали данные в PostgreSQL.

## Реализационные правила

Перед кодовой миграцией:

1. Создать удаленный fork/branch для SQLite-варианта от `sqlite-legacy-2026-06-15`.
2. Зафиксировать в README SQLite-fork, что он является legacy/small-install вариантом.
3. В основном репозитории добавить PostgreSQL-настройки и один `default` database alias.
4. Убрать постоянную зависимость бизнес-кода от `chat`, `knowledge_meta`, `analytics_control`.
5. Создать экспорт/импорт runtime-данных с manifest, счетчиками строк и проверкой внешних ключей.
6. Перевести FTS на PostgreSQL или временно отключить production search до завершения индексации.
7. Провести dry-run миграции на копии production-данных.

## Связанные материалы

- Проектный план: `docs/architecture/POSTGRESQL_PRIMARY_STORE_PLAN.md`.
- Active plan: `docs/planning/active/postgresql-primary-store-migration.md`.
- Исполнительный workflow: `workflow/active/postgresql-primary-store-migration/`.
- Runbook миграции: `docs/deployment/POSTGRESQL_MIGRATION.md`.
- Связанные ADR: ADR-0011, ADR-0015, ADR-0024.
