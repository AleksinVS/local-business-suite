# Отчёт исполнения 08: cleanup, recovery и финальная приёмка

Статус: **технически принято на тестовом хосте**. Пользовательская приёмка и
архивирование workflow ожидаются. Переключение production этим пакетом не
разрешалось и не выполнялось.

## Итог

- Все 13 документов `database_override` включены приватным allowlist тестового
  хоста. При отсутствии рабочей строки они читаются как проверенный Git-дефолт
  с revision `0`.
- Из `data/contracts/` удалены 30 тестовых JSON-файлов: 29 старых зеркал и одна
  тестовая резервная копия роли. Владелец явно разрешил удалить их без экспорта.
  Остались только `.memory-source-lifecycle.lock` и
  `.settings-contract-write.lock`.
- `bootstrap_runtime` после очистки создал 0 зеркал и скопировал 0 документов.
- `RuntimeSettingDocument` после приёмки пуст; тестовая ревизия recovery drill и
  соответствующая запись `SettingsChange` удалены после создания dump.
- Web и agent-runtime работают на итоговых тестовых образах. Django health и
  AI contract health имеют статус `ok`, AI delivery использует `source=gateway`
  без деградации.

## Реализованные изменения

- `bootstrap_runtime` больше не копирует `git_static` и
  `database_override`; каталоги и generated-артефакты остаются отдельным
  runtime-контуром.
- Реестр проверяет полный release set из 13 DB-документов. Архитектурный
  валидатор запрещает прямые settings/file reads и writes мигрированных путей
  вне централизованных адаптеров и проверяет полноту регистрации JSON-контрактов.
- Из agent-runtime удалён старый файловый путь `load_json`/
  `load_json_cached`; AI-контракты поступают только через Django gateway с
  проверкой schema/revision/hash и last-known-good.
- Docker-образ web устанавливает `git`, необходимый рабочему канону памяти.
- `access_administration_e2e` стал backend-aware. На PostgreSQL он создаёт
  временный документ внутри внешней транзакции, передаёт revision/hash CAS и
  откатывает документ, пользователей, группы и аудит независимо от результата.
  Постоянный PostgreSQL-тест проверяет отсутствие утечек.
- Документация отражает разделение Git-дефолтов, PostgreSQL overrides,
  generated data, backup/recovery и запрет постоянной двойной записи.

## Найденные и исправленные дефекты live-проверки

1. `memory_alignment_acceptance_e2e` выявил отсутствие `git` в web-образе.
   Зависимость добавлена в итоговый образ; повторный сценарий прошёл все семь
   стадий.
2. `access_administration_e2e` под активным DB backend продолжал готовить
   файловый fixture и не передавал `base_revision`. Сценарий переведён на
   транзакционный DB fixture с гарантированным rollback; повторный live e2e
   завершился без остаточных пользователей, групп, документов и аудита.

Независимое финальное ревью Sol high: **APPROVE**, блокирующих замечаний нет.
Неблокирующий риск существующей строки `RuntimeSettingDocument` покрыт
транзакционной семантикой, unit/PG-тестами и чистым live e2e, но не отдельным
вариантом permanent e2e с заранее существующим override.

## Recovery drill

Drill выполнен 2026-09-01 на тестовом PostgreSQL:

1. Через штатный `apply_contract_payload` временно создан
   `waiting_list.contract.status_colors` revision `1`, change id `17`.
2. Проверены document hash
   `20d4631e0303428f74477b4addd8530cd80886f2ad9dd67f5d42f514c7a19608`
   и default hash
   `348f37284afd0d7d81022ffa405839f27905423863c84eb2b7f2ed8d7c3c4dc9`.
3. Создан PostgreSQL custom-format dump, SHA-256
   `981c16c5a1617d75b0e27e1b2780b97024bb31b2b5b79d91d5e7441e8525fcc3`.
4. Тестовая строка и её audit удалены из действующей базы; состояние вернулось
   к 0 runtime documents и 6 исходным settings changes.
5. Dump восстановлен в отдельную БД `settings_recovery_drill_20260901`.
6. В восстановленной БД подтверждены schema `1`, revision `1`, совпадение
   canonical payload hash, `SettingsChange.after_hash`, after snapshot и audit
   continuity.
7. Состав 33 пользователей, 19 групп и их назначения совпали с исходной базой
   по трём SHA-256 контрольным суммам.
8. `ai.contract.chat_settings` в восстановленной БД и live agent-runtime имеют
   одинаковый hash
   `8902313a586da68bf060b42f9a519b8e4e83edc240ccbde44562bc062cd75f3a`
   и revision `0`; agent-runtime сообщает `source=gateway`.
9. `memory_sync_source --dry-run` на восстановленной БД успешно обработал семь
   источников без записи.
10. Временная БД и dump удалены. В `.local/` recovery-артефактов не осталось.

Drill не является экспортом удалённых legacy-тестовых файлов. Он проверяет
после переключения полноценное резервирование и восстановление PostgreSQL.

## Проверки

- Узкий registry/agent-runtime regression suite: **105 passed**.
- `make verify-profile PROFILE=contracts`: **62 passed, 126 deselected,
  2 subtests passed**.
- `make verify-full` с `--migrations --reuse-db`: **1120 passed, 61 skipped,
  218 subtests passed** за 143,34 с.
- `validate_architecture_contracts`: успешно для полного набора 13 DB-документов.
- Live e2e: `default_board_access_e2e`, `access_management_e2e`,
  `access_administration_e2e`, `memory_alignment_acceptance_e2e` и
  `memory_file_auto_organization_e2e` — успешно.
- Test-host health: Django `/health/` — `ok`; agent-runtime
  `/health/details` — `ok`, gateway, без деградации.
- `git diff --check`: успешно после оформления документации.

Все тесты повторно использовали существующую тестовую базу. Новая постоянная
тестовая БД не создавалась; единственная временная БД использовалась только как
изолированная цель обязательного recovery drill и затем удалена.

## Остаточные границы

- Production allowlist/cutover и удаление production legacy backup требуют
  отдельного разрешения, freeze, резервных копий и операционного окна.
- HIGH-риск bootstrap deidentification/PII остаётся отдельной security-задачей.
- До явной пользовательской приёмки план и workflow остаются в `active`, а
  запись не удаляется из backlog.
