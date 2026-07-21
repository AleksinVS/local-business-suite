# Task Acceptance: PostgreSQL Code Slice

Дата: 2026-06-15

## Решение

Кодовый срез миграции принят как готовый к dry-run на копии реальных данных.

## Принято

- Основной репозиторий больше не проектируется вокруг четырех SQLite database aliases.
- PostgreSQL является production target для реляционных моделей Django.
- SQLite остается dev/legacy вариантом и не включается в production без явного override.
- Search/queue production path переведен на таблицы основной БД.
- Документация и runbook описывают дальнейший порядок dry-run, cutover и rollback.

## Условия перед cutover

- Создать удаленный SQLite-fork из `sqlite-legacy-2026-06-15`.
- Выполнить `postgres_migration_export/import/validate` на копии настоящих runtime SQLite-файлов.
- Выполнить PostgreSQL `migrate`, `memory_reindex`, `memory_eval` и e2e на целевом профиле.
- Согласовать freeze window и rollback window.
