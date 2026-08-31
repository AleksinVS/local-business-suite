# Исполнительный отчёт: 02 PostgreSQL document store

## Результат

Добавлены модель текущей рабочей версии, единый repository и транзакционный
writer. Реальные документы ещё не переключены с legacy file backend: пакет
создаёт и проверяет инфраструктуру до pilot.

## Реализовано

- `RuntimeSettingDocument` и номера ревизий в `SettingsChange`;
- единый канонический SHA-256 без маскирования payload;
- aggregate repository read одним SQL-запросом для связанной группы;
- request-local snapshot, deep-copy и признаки degraded/migration_required;
- политики `fail_closed` и `visible_default_fallback`;
- PostgreSQL advisory locks с детерминированным signed 64-bit ключом;
- `revision + content_hash` CAS для первой и последующих записей;
- значение и applied audit в одной `transaction.atomic()`;
- rollback как новая монотонная ревизия;
- повторная проверка полномочий после получения lock;
- запрет writer на SQLite и read-only Django Admin;
- системная проверка backend;
- строгая канонизация JSON без неявного преобразования tuple и нестроковых
  ключей;
- единая проверка raw secret fields до записи и аудита;
- закрытый доменный срез без добавления несвязанных документов;
- health-сигналы `degraded`/`migration_required` без payload, путей и текста
  внутренних исключений;
- защитная reverse migration при непустом хранилище.

## Проверки

- совместный SQLite registry/repository matrix: 40 tests, PostgreSQL-only
  сценарии пропущены;
- PostgreSQL 17 на существующем тестовом сервере с `--keepdb`: **17 tests OK** —
  первая запись и update concurrency, monotonic history, rollback, audit
  rollback, stale CAS, sorted multi-document locks, schema/default drift,
  secret rejection, unique-race classification, permission recheck,
  cross-document concurrency и JSONB numeric round-trip;
- отдельный конкурентный сценарий одинакового operation fingerprint на
  несвязанных документах: **1 test OK**, один success и один типизированный
  conflict без частичной записи;
- `makemigrations --check --dry-run`: no changes;
- `validate_architecture_contracts`: успешно;
- существующие role catalog/file-backed сценарии: **3 tests OK**;
- `git diff --check`: успешно.

Отдельный PostgreSQL-контейнер не создавался. Production-данные и
`data/contracts/` не изменялись; Django переиспользовал существующую тестовую
БД.

## Независимое ревью

Первое Sol high ревью запросило исправления канонизации, health/fallback,
границы привилегированного среза, reverse migration, unique race, drift guard и
secret rejection. Второй цикл уточнил семантику связанной компоненты, повторную
проверку права rollback и cross-document concurrency. Все замечания реализованы
и покрыты тестами; третье Sol high ревью вынесло verdict **approve**.
