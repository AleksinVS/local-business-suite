# Отчёт исполнения 05: access/workflow security cutover

Статус: реализация и тестовый PostgreSQL cutover готовы; рабочее переключение
заблокировано до отдельного решения владельца по точным хешам `role_rules` и
операционного окна.

Дата: 2026-09-01.

## Результат

Связанный срез состоит ровно из трёх документов:

- `core.contract.role_rules`;
- `core.contract.workflow_rules`;
- `workorders.contract.status_colors`.

Все три ID выпущены в коде для DB allowlist, но в окружение автоматически не
добавляются. Текущий pilot листа ожидания остаётся независимым.

Для роли реализован предметный DB writer. Он сохраняет делегированный редактор
с `manage_roles` без требования `manage_settings`, подписанный preview,
optimistic CAS по `revision + content_hash`, operation fingerprint, privilege
ceiling и повторную авторизацию. Обычная запись и rollback не меняют
`$capabilities`, `$administration` и набор ролей. Создание и копирование роли
резервируют пустые `Group/GroupProfile` в той же транзакции, что документ и
аудит; пользователи, Django permissions и ACL не копируются.

Переходная сериализация access-домена использует порядок:

```text
access_control file lock
  -> transaction.atomic
  -> advisory locks всей связанной тройки по sorted document_id
  -> SELECT FOR UPDATE
  -> повторная авторизация/CAS/preview
  -> cross-validation
  -> Group + RuntimeSettingDocument + SettingsChange
```

HTTP middleware фиксирует один repository snapshot на запрос, включая старые
вызовы `get_contract()` без аргумента `request`. После успешной записи кэш
связанной компоненты удаляется, поэтому HTMX-ответ того же запроса видит новую
ревизию. `can_transition` дополнительно получает явный общий снимок role/workflow
и закрывается при недоступной конфигурации.

## Миграция роли

Живой preflight классифицировал роль как `security_review_required`, а workflow
и палитру заявок как `identical_default`. Безопасный storage target — точный
текущий runtime payload роли без автоматического добавления `$defaults` или
`viewer`. Для него добавлен явный apply только при одновременном совпадении:

- compact hash текущего runtime;
- compact hash Git-default;
- `$capabilities` и `$administration` runtime с Git-default;
- повторного plan под общей блокировкой.

Решение и оба хеша записываются в `SettingsChange.validation_result`. Любой дрейф
между plan, backup и INSERT откатывает всю транзакцию. Общий apply по-прежнему
не принимает `security_review_required` без этих параметров.

Deployment-команда изменения capability catalog адаптирована к DB backend: она
принимает только reviewed candidate, проверяет три нормализованных хеша,
разрешает изменения только каталога и соответствующих значений ролей, обновляет
payload/revision/default hash и аудит одной транзакцией. Исторический catalog
обычным rollback не восстанавливается. Legacy-команда удаления
`$administration` сохраняет файловый путь для legacy backend, а после DB
cutover использует отдельный constrained DB writer.

## Проверки

Выполнено без создания новой тестовой базы (`--reuse-db`):

- SQLite Settings Center: **230 passed, 43 skipped, 92 subtests passed**;
- accounts/workorders/waiting-list/inventory: **290 passed, 5 deselected,
  20 subtests passed**;
- PostgreSQL access/migration/request snapshot: **56 passed, 1 skipped,
  11 subtests passed**;
- PostgreSQL document repository/writer: **34 passed, 1 skipped,
  5 subtests passed**;
- отдельный PostgreSQL access HTTP/service e2e: **10 passed**;
- architecture/transition slice: **10 passed**;
- `compileall`, `manage.py check` и `git diff --check` успешны; локальное
  предупреждение `settings_center.W002` относится к недоступному PostgreSQL при
  SQLite-проверке.

Постоянные тесты покрывают partial allowlist, request snapshot, cache
invalidation, role create/copy/default, delegated edit, поздний rollback группы,
frozen catalog, deployment migration, workflow cross-validation, HTTP create и
workflow matrix, exact-hash security import, stale/concurrent writer и audit
atomicity.

## Не выполнено намеренно

- allowlist access-среза в `.env` не изменён;
- живая DB-строка роли не создана;
- legacy-файлы и тестовые/рабочие данные не удалены этим пакетом;
- `viewer` не активирован;
- production freeze, backup, apply, restart и observation не выполнялись.

Следующий операционный шаг возможен только после явного выбора владельца,
повторного final plan и выполнения runbook
`docs/deployment/SETTINGS_DOCUMENTS_MIGRATION.md`.

## Correction cycle после независимого REJECT

Добавлен явный `ConfigDocumentRepository.get_fresh_document/get_fresh_snapshot`:
он обходит request-local cache и используется после access lock в назначении
ролей, изменении состава роли, ACL доски и автоматическом назначении роли новому
пользователю. Подписанные previews этих операций теперь содержат одновременно
`role_contract_hash` и `role_contract_revision`; apply сравнивает оба значения с
новым снимком. Добавлен SQLite race-тест: устаревший снимок запроса не позволяет
применить preview после изменения DB-ревизии.

`migrate_role_administration_metadata` получил отдельный DB writer на базе
ограниченного migration API: активный суперпользователь, обязательная причина,
точные runtime/Git хеши, запрет `$administration` в Git и проверка кандидата,
удаляющего только этот блок. Порядок блокировок — access lock, транзакция,
PostgreSQL advisory/row locks; backup, runtime row и `SettingsChange` проходят
один guarded write, а backup удаляется при откате аудита. Legacy path сохранён.

Access/role views централизованно возвращают непрозрачный HTTP 503 при
`ConfigurationUnavailable`/`DocumentRepositoryError`; payload и пути в ответ не
попадают. `prepare_explicit_viewer_migration` отклоняет активный DB role backend
до подготовки групп или ACL. Static architecture test дополнительно запрещает
`getattr(settings, ...)` и прямое чтение migrated role/workflow/status-color
контрактов вне migration boundary.

Correction checks (без создания новой БД, только `--reuse-db`):

- request snapshot, race, UI 503 и viewer guard: **6 passed, 6 skipped** на SQLite;
- accounts/workorders access assignment and board ACL: **9 passed**;
- access database/document repository slice: выбранные SQLite-тесты **успешны**;
  DB writer PostgreSQL tests skipped в SQLite окружении;
- architecture management command и static consumer check: **успешно**;
- `py_compile` затронутых модулей и `git diff --check`: **успешно**.

Остаточный риск: PostgreSQL advisory/row-lock, DB deployment success и audit
rollback не воспроизведены локально из-за отсутствия PostgreSQL; они оставлены
как `skipUnless(postgresql)` тесты для CI/операционного окна.

Финальная последовательная перепроверка после correction cycle: account/workorder
access tests — **9 passed**, request snapshot — **6 passed, 6 skipped**, static
consumer/document repository checks — **2 passed**; `py_compile` и `git diff
--check` также успешны. Параллельный запуск SQLite-наборов один раз получил
только ожидаемую блокировку общей reuse-базы; тот же набор последовательно
завершился успешно.

## Финальная коррекция после Sol-review

В `_repair_role_materialization` после получения access-lock выполняется
свежий DB-read через `get_fresh_document("core.contract.role_rules")` для
активного database backend. Сравниваются актуальные content hash и revision с
ожидаемыми значениями старого снимка, затем повторно проверяются полномочия и
политика целевой роли. Для legacy backend сохранён эквивалентный no-cache
прочитанный файл без принудительной загрузки отсутствующих в deployment
связанных Git-дефолтов. Добавлен тест гонки, в котором роль меняется между
request snapshot и repair lock: устаревшая конфигурация не материализует
`Group`.

`prepare_explicit_viewer_migration`, `cutover_explicit_viewer` и
`rollback_explicit_viewer` получили общий ранний guard. При DB backend роли
каждая legacy-фаза завершается fail-closed, включая ранее подписанный и
подготовленный manifest, до actor refresh, membership, board ACL или artifact
write. Регрессионный тест проверяет отсутствие изменений membership и ACL для
обоих вызовов.

`ConfigDocumentRepository` преобразует `DatabaseError` на границе
`QuerySet.in_bulk()` в `ConfigurationUnavailable` с безопасным внутренним
cause и сигналом `database_unavailable`. Safe Settings Center UI возвращает
непрозрачный HTTP 503, а `SettingDetailView.get_initial` больше не помещает
текст исключения в JSON-поле. Добавлены boundary-тест `in_bulk` и HTTP-тест
без раскрытия пути или payload.

Проверка пустого backup-каталога в access database slice допускает оба
безопасных состояния — каталог отсутствует или существует пустым; production
код удаления каталогов не добавлялся. Руководство
`SETTINGS_CENTER_OPERATIONS.md` уточняет порядок: viewer migration завершается
до access DB cutover, после которого legacy prepare/cutover/rollback запрещены;
DB writer для `$administration` остаётся отдельной deployment-операцией.

Финальные узкие проверки (существующая база, без `--create-db`):

- `pytest apps/settings_center/test_access_request_snapshot.py apps/settings_center/test_document_repository.py --reuse-db --maxfail=1 -r a` — **27 passed, 27 skipped, 7 subtests passed**;
- `pytest apps/settings_center/test_access_database_slice.py --reuse-db --maxfail=1 -r a` — **1 passed, 12 skipped**;
- `pytest apps/settings_center/tests.py -k 'materializes_group_idempotently or each_migration_phase_recovers_from_audited_partial_state or setting_detail_shows' --reuse-db --maxfail=1` — **3 passed**;
- `py_compile` затронутых модулей и `git diff --check` — успешно.

## PostgreSQL перепроверка положительного repair-теста

Первый PostgreSQL запуск положительного теста корректно остановился в
`save_role_creation`: тестовый candidate содержал опечатку в `display_name`
(`Восстановляемая роль`), а повторный вызов передавал `Восстанавливаемая роль`.
Это было расхождение входных данных теста, а не idempotency-дефект production
кода. Тест приведён к единым переменным `display_name`/`description`; проверки
hash/revision и политики не ослаблялись.

На существующей `test_local_business_suite` PostgreSQL базе, без создания БД,
выполнено с `--reuse-db`:

- failing node после исправления — **1 passed**;
- весь `test_access_database_slice.py` — **14 passed** за 18.38 секунды.

Временная диагностика удалена; в production-коде после этого анализа изменений
не потребовалось.

Остаточный риск не изменился: PostgreSQL advisory/row-lock, реальный
PostgreSQL `in_bulk` failure и DB deployment/audit rollback требуют CI или
операционного PostgreSQL окна; локально соответствующие тесты остаются
`skipUnless(postgresql)`. Production cutover и viewer activation не выполнялись.

## Повторная финальная коррекция после Sol-review

Исправлена граница хешей в repair-пути: `save_role_creation` передаёт
`snapshot.content_hash`, а `_repair_role_materialization` сравнивает его с
`RuntimeSettingSnapshot.content_hash`. Это единый transport-формат для
compact DB hash и legacy snapshot; `normalized_hash(payload)` больше не
смешивается с compact document hash.

Race-тест теперь явно проверяет, что между старым request snapshot и repair
lock изменились одновременно revision и content hash, после чего stale role не
материализуется. Добавлен положительный PostgreSQL test для уже существующей
роли в `RuntimeSettingDocument`: при неизменных revision/hash и отсутствующей
`Group` повторный `save_role_creation` создаёт `Group/Profile`, не создаёт
`SettingsChange` и не увеличивает revision.

Документация однозначно фиксирует, что после access DB cutover legacy file
variant `$administration` запрещён; команда `migrate_role_administration` в
этом режиме маршрутизирует операцию в constrained DB writer и не меняет
legacy-файл.

Проверки этой коррекции с существующей базой и `--reuse-db`:

- `pytest apps/settings_center/test_access_request_snapshot.py apps/settings_center/test_document_repository.py --reuse-db --maxfail=1 -r a` — **27 passed, 27 skipped, 7 subtests passed**;
- `pytest apps/settings_center/test_access_database_slice.py --reuse-db --maxfail=1 -r a` — **1 passed, 13 skipped** (положительный DB repair test собран и ожидаемо skipped без PostgreSQL);
- PG-node `AccessRequestSnapshotPostgresTests.test_role_materialization_repair_reloads_db_after_stale_request_snapshot` также собран; локально ожидаемо **1 skipped** с причиной `requires PostgreSQL`, поэтому race входит в PostgreSQL-прогон CI;
- `pytest apps/settings_center/tests.py -k 'materializes_group_idempotently or each_migration_phase_recovers_from_audited_partial_state or setting_detail_shows' --reuse-db --maxfail=1` — **3 passed**;
- `py_compile` затронутых модулей и `git diff --check` — успешно.
