# Executor report 07: memory/FileHub snapshots и static classification

## Методическая заметка

Снимок конфигурации — это чтение согласованной ревизии документа в начале
операции. Дальше профиль передаётся в функции обработки объектов как обычное
значение; поэтому изменение рабочего документа влияет на следующую операцию,
но не меняет правила в середине текущего обхода.

## Выполнено

- Добавлен memory-адаптер `get_memory_document_snapshots()` и чтение payload через
  `ConfigDocumentRepository`, без загрузки migrated memory payload из startup
  constants. Для существующих Django-тестов сохранена поддержка явного
  `override_settings` только при наличии `UserSettingsHolder`.
- Ingestion/discovery, reindex и `memory_sync_source` фиксируют ingestion/source
  snapshot в начале команды; item loops повторно repository не читают. Для
  векторной индексации профиль embeddings передаётся в тот же backend snapshot.
- Поиск фиксирует единый снимок profiles/routing/trust/retrieval budget; route,
  ranking и context budget используют именно его. Trust и routing сохраняют
  закрытый отказ при недоступности документа.
- `relations:`/graph schema validator и materializer получают один snapshot
  graph schema на проход.
- FileHub baseline, incoming, proposal review, move worker и purge получают
  один profile snapshot на операцию/job. Move worker передаёт профиль в каждое
  задание и не перечитывает документ в цикле.
- Claims policy уже классифицирована в доменном `ConfigDocumentSpec` как
  `git_static`; analytics documents и `core.integration.registry` также имеют
  `git_static`, owner и read-only policy. Для аналитики добавлен узкий reader
  adapter: сервисы используют repository/spec, а legacy file overrides остаются
  только тестовым compatibility path. DB writer для статических документов не
  добавлялся.
- Добавлены архитектурные тесты на отсутствие прямых startup payload reads и
  на snapshot API/profile boundaries.

## Correction cycle после REJECT

- Удалены startup payload assignments `LOCAL_BUSINESS_MEMORY_*` из
  `config/settings.py`; оставлены только пути и скалярные process/deployment
  настройки. `_test_override_payload` теперь принимает только явно записанные
  на `UserSettingsHolder` тестовые атрибуты: обычный `override_settings(DATA_DIR=...)`
  не подменяет repository snapshot. Аналогичное правило действует для
  analytics reader.
- `validate_architecture_contracts` читает единый effective snapshot scope для
  memory, analytics и integration registry; проверки parity выполняются по
  этим payload, а не по settings paths. `memory_sources` cross-validator в
  Settings Center получает связанные документы одним repository snapshot.
- Claims policy закреплена как `git_static`/`read_only` с viewer-виджетом;
  graph schema descriptor отражает `requires_domain_workflow`; из memory
  descriptors удалён `settings_payload_attr`. `bootstrap_runtime` больше не
  зеркалирует git-static и уже переведённые database документы.
- Startup payload assignments для analytics и integration registry также
  удалены из `config/settings.py`; оставлены только file-path настройки для
  explicit test/deployment compatibility. Static analytics и integration
  specs больше не публикуют `legacy_settings_path` в registry/contract drift;
  добавлены parity-проверки этого запрета.
- Release gate зарегистрировал ровно восемь готовых memory
  `database_override` IDs (sources, profiles, routing, trust policy, retrieval
  budget, ingestion profiles, FileHub profiles и graph schema); claims policy
  исключена. Приватный deployment allowlist не изменён и остаётся отдельным
  решением окружения.
- Ошибки `ConfigurationUnavailable`/`DocumentRepositoryError` vector
  backend не подавляются. ACL с unresolved policy получает явный job
  snapshot/profile, а при отсутствии обоих вариантов закрывается без
  permissive scalar fallback.
- `source_adapter_reconcile`, `memory_reindex`, `memory_reconcile` и legacy
  migration захватывают profiles/sources/ingestion snapshot до item loop и
  передают его во все projection/index/delete вызовы. Discovery и ingestion
  сравнивают `MemorySource` projection с тем же source contract snapshot и
  останавливаются при stale mismatch. Retrieval передаёт snapshot через
  object access/text rendering, поэтому ACL не читает repository внутри
  candidate loop.
- FileHub public `execute_move_job` и worker path передают один profile
  snapshot/profile до физической операции; review accept/reject и index delete
  также владеют одним operation snapshot. Chat memory/index helpers принимают
  явный snapshot.
- Изменение DB memory setting с `requires_reindex` регистрирует
  `transactional_outbox_callback`. Writer вызывает его после документа и
  `SettingsChange`, но внутри той же транзакции; callback создаёт
  `MemoryExternalConnectorJob` с идемпотентным ключом
  `settings-memory-reindex:<document>:<revision>:<hash>`. Ошибка вставки,
  domain rollback и внешний rollback откатывают очередь вместе с документом;
  тяжёлый reindex не запускается внутри транзакции.
- Отсутствующий в captured `memory.contract.sources` источник теперь
  останавливает discovery/ingestion до filesystem/index side effects. Для
  существующих тестовых fixture источников добавлен явный test-only allowlist;
  production fallback отсутствует.

## Correction cycle после REJECT Sol high

- Во всех nullable FileHub/Memory review lock paths (`file_organization_stats`,
  `file_organization`, `file_organization_move`, `review_services`) сначала
  блокируется базовая строка `select_for_update()`, а nullable relations
  загружаются вторым обычным запросом. Это устраняет PostgreSQL outer-join
  `NotSupportedError` и сохраняет stale/concurrency guard.
- `memory_reconcile` захватывает profiles и graph-schema одним снимком до
  item loop; materializer получает тот же снимок. Полный source sync атомарно
  отключает отсутствующие projections, а для каждой реальной смены в disabled
  ставит одно idempotent `source_cleanup` задание; partial `--source-code`
  остальные источники не отключает. Queue worker применяет source settings
  только при совпадении revision/hash и повторный cleanup безопасен.
- Retrieval захватывает `memory.contract.sources`, пересекает requested source
  codes с enabled contract codes и не выдаёт enabled stale DB projection,
  отсутствующий в текущем source snapshot. Source-data fallback передаёт тот
  же snapshot в scope/trust/adapter gates.
- Постоянный FileHub e2e больше не меняет settings holder: он создаёт явно
  scoped source projection и передаёт source/ingestion/FileHub snapshots во все
  вызовы. Production source mismatch остаётся fail-closed.
- Callback metadata переименован в `transactional_outbox_callback`, доменный
  enqueue — в `enqueue_memory_reindex_outbox`; добавлены PostgreSQL-oriented
  tests для apply, domain/outer rollback, audit/queue insert failure,
  duplicate и batch writes. Добавлен worker test для source revision sync,
  missing-source cleanup и idempotency.

## Correction cycle после main PG REJECT

- Добавлен единый `validate_locked_current_file_state`: перед созданием или
  исполнением move-задачи он проверяет current pointers, принадлежность version
  и placement тому же `MemoryFileObject`, статус version `CURRENT`,
  `placement.is_current`, совпадение source object у обеих связей и принадлежность
  source object ожидаемому `MemorySource`. В `_build_approved_snapshot`, single
  и batch move children сначала блокируются отдельными стабильными запросами;
  final pre-I/O validation использует тот же helper. Nullable `FOR UPDATE`
  joins не добавлялись.
- Добавлен creation-path regression: foreign version, foreign placement,
  mismatched source object и non-current version отклоняются до создания job;
  неизменённая valid chain создаёт ровно одну PLANNED job. Существующий final
  validator test дополнен теми же негативными вариантами.

## Correction cycle после main PG REJECT: locked file-state invariant

- Добавлен общий `validate_locked_current_file_state` для всех путей создания и
  исполнения физических move jobs. Он fail-closed проверяет parent current
  pointers, принадлежность version/placement тому же `MemoryFileObject`,
  `version_status=CURRENT`, `placement.is_current`, совпадение source object у
  обеих связей и принадлежность source object ожидаемому `MemorySource`.
  `_build_approved_snapshot`, single/batch job creation и final pre-I/O state
  validation используют один helper.
- Nullable FK relations не участвуют в `FOR UPDATE` outer join: parent files,
  versions, placements и source objects блокируются раздельными запросами в
  стабильном порядке, после чего parent pointers перепроверяются.
- Добавлены creation-path негативные тесты для foreign version, foreign
  placement, mismatched source object и non-CURRENT version: до corrupt state
  не появляется job; valid unchanged chain создаёт ровно одну PLANNED job.

Main-agent acceptance на PostgreSQL (результаты переданы в этот report, а не
запускались в локальной SQLite-копии): 33 settings/snapshot/source теста,
широкий PG набор FileHub/analytics/ingestion/privacy и host git/AI identity
прошли; постоянный `memory_file_auto_organization_e2e` на PG прошёл. В main
correction отдельно устранён `IndexStatus.PENDING` и тестовые identity fixtures
сделаны явно scoped. Эти результаты не означают включение приватного
deployment allowlist.

Остаточный риск: privacy/PII-поведение bootstrap package намеренно не менялось
в этом correction cycle (это non-goal пакета и найденный существующий HIGH).
Нужен отдельный security packet; текущая задача не расширяет его scope.

## Изменённые файлы

- `apps/memory/config_documents.py`
- `apps/memory/chat_memory.py`
- `apps/memory/document_ingestion.py`
- `apps/memory/embeddings.py`
- `apps/memory/knowledge_edges.py`
- `apps/memory/policies.py`
- `apps/memory/retrieval.py`
- `apps/memory/vector_backends.py`
- `apps/memory/routing.py`
- `apps/memory/management/commands/memory_eval.py`
- `apps/memory/management/commands/memory_reindex.py`
- `apps/memory/management/commands/memory_sync_source.py`
- `apps/memory/management/commands/memory_reconcile.py`
- `apps/memory/management/commands/memory_migrate_legacy_knowledge.py`
- `apps/memory/management/commands/source_adapter_reconcile.py`
- `apps/memory/review_services.py`
- `apps/memory/selectors.py`
- `apps/memory/tests/_common.py`
- `apps/memory/tests/test_storage_snapshots.py`
- `apps/memory/tests/test_settings_reindex.py` (PostgreSQL release-gate tests)
- `apps/filehub/file_organization.py`
- `apps/filehub/file_organization_baseline.py`
- `apps/filehub/file_organization_incoming.py`
- `apps/filehub/file_organization_move.py`
- `apps/filehub/file_organization_stats.py`
- `apps/filehub/tests.py` (creation-path current-chain regressions)
- `apps/analytics/config_documents.py` (reader adapter для уже static-документов)
- `apps/analytics/services.py` (перевод трёх contract readers на adapter)
- `apps/core/management/commands/bootstrap_runtime.py`
- `apps/core/management/commands/validate_architecture_contracts.py`
- `apps/core/config_documents.py` (integration registry static без legacy path)
- `apps/core/tests.py`
- `apps/settings_center/descriptors.py`
- `apps/settings_center/document_registry.py` (выпущен connected memory DB slice)
- `apps/settings_center/document_specs.py` (transactional outbox callback metadata)
- `apps/settings_center/document_services.py` (in-transaction outbox registration)
- `apps/memory/management/commands/memory_queue_worker.py`
- `apps/filehub/management/commands/memory_file_auto_organization_e2e.py`
- `config/settings.py`
- `docs/deployment/MEMORY_DEPLOYMENT.md`
- `docs/guides/MEMORY_INGESTION_OPERATIONS.md`
- `docs/guides/SETTINGS_CENTER_OPERATIONS.md` (memory DB-ready slice и durable outbox)

## Проверки

Успешно:

- `python3 -m compileall -q apps/memory apps/filehub`
- `git diff --check`
- `../../.venv/bin/python -m pytest apps/memory/tests/test_ingestion.py apps/memory/tests/test_reconcile_and_edges.py apps/filehub/tests.py --reuse-db --maxfail=1 -m 'not slow'` — 68 passed, 36 subtests
- `../../.venv/bin/python -m pytest apps/memory/tests/test_indexing.py apps/memory/tests/test_policy_and_privacy.py apps/memory/tests/test_sources_and_models.py --reuse-db --maxfail=1 -m 'not slow'` — 30 passed, 5 subtests
- `../../.venv/bin/python -m pytest apps/memory --reuse-db --maxfail=1 -m 'not slow'` — 116 passed, 37 subtests
- `../../.venv/bin/python -m pytest apps/filehub/tests.py --reuse-db --maxfail=1 -m 'not slow'` — 44 passed, 28 subtests
- `../../.venv/bin/python -m pytest apps/memory/tests/test_storage_snapshots.py --reuse-db --maxfail=1` — 4 passed
- `../../.venv/bin/python -m pytest apps/analytics/tests.py --reuse-db --maxfail=1 -m 'not slow'` — 8 passed
- `../../.venv/bin/python manage.py memory_eval --dry-run` — passed=6, failed=0
- `../../.venv/bin/python manage.py validate_architecture_contracts` — valid; drift report: 18/18 совпадают с дефолтами

После correction cycle:

- `../../.venv/bin/python -m pytest apps/memory/tests/test_storage_snapshots.py --reuse-db --maxfail=1` — 13 passed
- `../../.venv/bin/python -m pytest apps/memory/tests/test_settings_reindex.py --reuse-db --maxfail=1` — 3 skipped (локальный SQLite; writer требует PostgreSQL/released slice; тест сам задаёт полный connected allowlist)
- `../../.venv/bin/python -m pytest apps/memory/tests/test_storage_snapshots.py apps/settings_center/test_document_registry.py apps/memory/tests/test_settings_reindex.py --reuse-db --maxfail=1 -m 'not slow'` — 27 passed, 3 skipped, 3 subtests (локальный SQLite)
- `../../.venv/bin/python -m pytest apps/memory/tests/test_chat_knowledge.py apps/filehub/tests.py --reuse-db --maxfail=1 -m 'not slow'` — 52 passed, 28 subtests
- `../../.venv/bin/python -m pytest apps/memory --reuse-db --maxfail=1 -m 'not slow'` — 125 passed, 37 subtests
- `../../.venv/bin/python -m pytest apps/filehub/tests.py --reuse-db --maxfail=1 -m 'not slow'` — 44 passed, 28 subtests
- `../../.venv/bin/python -m pytest apps/analytics/tests.py --reuse-db --maxfail=1 -m 'not slow'` — 8 passed
- `../../.venv/bin/python -m pytest apps/core/tests.py -k 'BootstrapRuntimeCommandTests or SettingsImportSideEffectTests' --reuse-db --maxfail=1 -m 'not slow'` — 4 passed
- `../../.venv/bin/python -m pytest apps/settings_center/test_document_registry.py apps/settings_center/tests.py -k 'registry or descriptor or runtime_validator' --reuse-db --maxfail=1 -m 'not slow'` — 41 passed, 8 subtests
- `../../.venv/bin/python -m pytest apps/filehub/tests.py apps/memory/tests/test_storage_snapshots.py apps/analytics/tests.py --reuse-db --maxfail=1 -m 'not slow'` — 66 passed, 28 subtests
- `../../.venv/bin/python -m pytest apps/filehub/tests.py apps/memory/tests/test_reconcile_and_edges.py apps/memory/tests/test_ingestion.py apps/memory/tests/test_policy_and_privacy.py --reuse-db --maxfail=1 -m 'not slow'` — 80 passed, 36 subtests
- `../../.venv/bin/python -m pytest apps/memory/tests/test_indexing.py apps/memory/tests/test_sources_and_models.py apps/memory/tests/test_storage_snapshots.py apps/memory/tests/test_reconcile_and_edges.py --reuse-db --maxfail=1 -m 'not slow'` — 51 passed, 5 subtests
- `../../.venv/bin/python -m pytest apps/memory/tests/test_sources_and_models.py apps/memory/tests/test_storage_snapshots.py apps/filehub/tests.py --reuse-db --maxfail=1` — 70 passed, 33 subtests
- `../../.venv/bin/python -m pytest apps/memory/tests/test_settings_reindex.py --reuse-db --maxfail=1` — 7 skipped (локальный SQLite; весь PostgreSQL writer/outbox suite не пропускается на целевой PG)
- `../../.venv/bin/python -m pytest apps/filehub/tests.py --reuse-db --maxfail=1 -m 'not slow'` (после locked-state correction) — 45 passed, 32 subtests
- `../../.venv/bin/python -m pytest apps/filehub/tests.py::MemoryFileHubScopeBoundaryTests::test_move_creation_rejects_corrupt_current_chain_before_job apps/filehub/tests.py::MemoryFileHubScopeBoundaryTests::test_claim_lock_order_and_validator_reject_foreign_or_unsafe_chain --reuse-db --maxfail=1` — 2 passed, 4 subtests
- `../../.venv/bin/python manage.py memory_eval --dry-run` — passed=6, failed=0
- `../../.venv/bin/python manage.py validate_architecture_contracts` — valid; warning only: settings document migration state unavailable
- `python3 -m py_compile` — целевые memory/FileHub/settings writer модули успешно скомпилированы
- `rg` lock scan — опасных цепочек `select_for_update().select_related()` и старых outbox API не найдено
- `git diff --check` — успешно
- `../../.venv/bin/python manage.py memory_reindex --dry-run --corpus all --backend fulltext` — не выполнено: локальная runtime SQLite БД без таблицы `memory_memorysearchdocument`; новую БД не создавал.

Команды matrix dry-run (`memory_sync_source`, `memory_reindex`,
`memory_reconcile`) и FileHub e2e не завершены в этой рабочей копии: локальная
runtime SQLite БД не содержит таблиц (`no such table: memory_memorysource`,
`memory_memorysearchdocument`, `memory_memoryknowledgeitem`, `auth_group`).
Создание новой БД запрещено условиями пакета; тестовые прогоны выше выполнены с
`--reuse-db` через pytest.

## Документация и ограничения

Документация пакета уже отражала основные ограничения memory/FileHub, но в
correction cycle deployment/operations guide уточнены под effective repository
snapshots и static classification; обновлён также этот executor report. Новые
ADR не требовались. Knowledge canon,
`contracts/`, `data/`, AI/runtime и настройки deployment не изменялись. Коммит и
push не выполнялись.
