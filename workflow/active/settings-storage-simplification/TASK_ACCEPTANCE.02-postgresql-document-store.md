# Приёмка пакета 02: PostgreSQL document store

Статус: **Accepted**  
Дата: 2026-08-31

## Принятый результат

- `RuntimeSettingDocument` хранит текущую ревизию, schema/default/content hash и
  автора; `SettingsChange` хранит номера ревизий до/после;
- repository читает Git/legacy/database через одну спецификацию, проверяет JSON,
  секреты, schema/hash, доменный и связанный валидаторы, сохраняет единый снимок
  на запрос;
- PostgreSQL writer использует отсортированные advisory locks, `select_for_update`,
  revision+hash CAS и одну транзакцию для значения и применённого аудита;
- документы одной связанной компоненты блокируются и валидируются вместе, но
  сохраняют независимые границы изменения и rollback;
- `fail_closed`, видимый fallback, `migration_required` и privacy-safe health
  реализованы без раскрытия payload, путей и внутренних ошибок;
- raw secrets запрещены в defaults, DB rows, кандидатах и audit context;
- reverse migration запрещена при непустом хранилище.

## Доказательства

- SQLite repository/backend matrix: 34 tests OK, 17 PostgreSQL-only пропущены;
- PostgreSQL correction matrix: 17 tests OK;
- конкурентный operation fingerprint: 1 test OK;
- legacy role catalog/file writer regression: 3 tests OK;
- `validate_architecture_contracts`, `makemigrations --check --dry-run` и
  `git diff --check`: успешно.

## Независимая проверка

Sol high провёл три read-only цикла database/concurrency/security review. После
двух correction cycles итоговый verdict — **approve**, блокирующих замечаний нет.

## Остаточный риск

Полный migration lifecycle на свежей PostgreSQL БД и восстановление reverse
проверяются в пакетах 03 и 08. Реальные доменные документы ещё не переключены;
production-данные не изменялись.
