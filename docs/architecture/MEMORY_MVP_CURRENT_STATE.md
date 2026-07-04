# Текущее состояние MVP памяти

Дата: 2026-06-15.

Этот документ фиксирует фактическую рабочую границу системы памяти. Целевые планы и ADR остаются источником решений "куда идем", но текущий runtime нужно сверять с этим описанием.

## Рабочий путь знания

Основной путь принятого знания сейчас такой:

```text
memory.remember
  -> MemoryWriteRequest
  -> MemoryIndexJob
  -> knowledge_writer_worker / process_queued_memory_requests
  -> data/knowledge_repo/**/*.md
  -> MemoryKnowledgeItem
  -> MemorySearchDocument
  -> full-text index selected by LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND
  -> optional LanceDB vector index
  -> memory.search
```

Текст принятого знания хранится только в файле знания в `data/knowledge_repo/`. `MemoryKnowledgeItem` хранит метаданные, права, статус, хэши и ссылки на источник. `MemorySearchDocument` является технической карточкой индекса и не является источником истины для текста.

### Приведение к канону (ADR-0030, этап 1 — в процессе)

Идет переход к модели «файл знания — канон» (ADR-0030). На этапе 1 уже действует:

- **Кроссплатформенная блокировка записи** в `knowledge_repo` (`fcntl` на POSIX, `msvcrt` на Windows) вместо прежней `fcntl`-only реализации, которая на Windows была no-op.
- **Чистота канона:** frontmatter больше не несет производного состояния (`index_status`, собственные хэши); оно остается в проекции (инвариант №9). Frontmatter несет `lifecycle` (workflow-флаг).
- **Pull-reconciler** `python manage.py memory_reconcile` (`--dry-run`, `--force`): по content-hash гейту пересобирает проекции измененных файлов; идемпотентен; ручная правка не ломает чтение; понижение `sensitivity` ручной правкой держится `pending` (только вверх автоматически).
- **Двойная работа и откат:** авторитет файла-канона включается флагом `LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE` (по умолчанию выключен — проекция авторитетна, хэши валидируются). Переключение — после чистой `memory_verify_knowledge_files`; откат — возврат флага.

Путь записи (`memory.remember` через очередь) на этапе 1 не меняется — это задача этапа 2.

## Что работает

- Очередь `memory.remember` через `MemoryWriteRequest` и `MemoryIndexJob`.
- Персональные и организационные знания из AI-чата.
- Secret handles: секретное значение не пишется в знание, индекс, audit и результат поиска.
- Runtime Git-репозиторий знаний `data/knowledge_repo/`.
- Единая основная БД для chat, memory metadata и analytics control; production target - PostgreSQL.
- Поиск через `memory.search` по корпусу `knowledge`.
- Явный и fallback-показ `source_data` как ссылок на исходные объекты.
- Trusted-only gate для обычного контекста агента.
- `MemoryAccessAudit` для разрешенных и запрещенных поисков.
- Ingestion MVP для local/UNC источников, текстовых файлов и табличных `.csv/.tsv/.xlsx/.xls` с issue queue.
- PostgreSQL full-text backend в production; SQLite FTS5 остается dev/legacy fallback.
- LanceDB vector backend с локальным embedding provider; по умолчанию используется легкий deterministic test profile, production-профиль включается через `LOCAL_BUSINESS_MEMORY_EMBEDDING_PROFILE`.
- Документный индекс: результат поиска возвращает документ, а не раздел/фрагмент.
- Graph schema bootstrapping и extraction-команды как отдельный подготовительный контур.
- Reference implementation внешнего коннектора: envelope, database/sqlite queue backends, landing zone, retention cleanup и handoff.
- Универсальные source adapters для внутренних модулей: `workorders` и `waiting_list` отдают `SourceObjectEnvelope`.
- `source_adapter_reconcile` строит из envelope проекции `MemorySourceObject`, `MemorySearchDocument`, FTS/vector index и analytics projection.
- Для `adapter_check` источников выдача `source_data` выполняет финальную проверку доступа через доменный адаптер; при отсутствии адаптера результат fail-closed.
- Privacy defaults для source adapters: PII по умолчанию выключено, внешние источники могут явно включать `pii_guarded`; secret scanning всегда включен.
- AI-инструмент `workorders.search` ищет по индексированным заявкам через `memory.search` в режиме `source_explicit`.
- Автоупорядочивание файлового источника: stable `MemoryFileObject`, версии, история физических путей, baseline virtual structure, incoming worker, пользовательский UI `/memory/files/`, агрегированные proposals, `managed_fs` copy/verify/quarantine и блокировка purge без backup checkpoint.

## Что не работает как runtime MVP

- Graph runtime search в `memory.search`.
- OCR изображений и сканов.
- Фрагментный поиск по крупным разделам документа.
- Production parser cascade для PDF/DOC/DOCX и OCR.
- Production multilingual embedding model не скачивается и не включается автоматически.
- Claim/belief lifecycle.
- MLflow/Ragas/DeepEval quality tracing.
- Source-specific production connector для внешней ИС.
- Внешний HTTP API памяти.
- S3/S3-compatible backend для файлового автоупорядочивания.
- Автоматическое физическое перемещение без администраторского согласования.

Эти контуры не удалены из ADR и долгосрочных планов, но в текущем runtime они должны отображаться как `planned`, `disabled` или `not_ready`.

## `knowledge` и `source_data`

`knowledge` - это принятое знание. Обычный ответ агента должен опираться именно на этот корпус.

`source_data` - это исходные объекты и ссылки на них: файлы, API envelopes, документы источников. Они могут быть найдены явно или как fallback, но результат `source_data` не является принятым знанием и должен показываться с предупреждением.

Система не должна записывать полный извлеченный текст исходного файла в `MemorySearchDocument.metadata`.

## `data/memory/chat_knowledge/`

`data/memory/chat_knowledge/` оставлен только как legacy append-only event log для событий памяти из чата.

Он не является источником истины для текста знания. Канонический текст знания находится в `data/knowledge_repo/`, а метаданные - в `MemoryKnowledgeItem`.

## External connector

Generic external connector MVP считается reference implementation. Его можно использовать для тестов и подготовки pilot, но развитие source-specific adapter и production sync начинается только после выбора pilot source, владельца данных, правил доступа, sensitivity и retention.

## Проверки текущей границы

Базовые проверки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_eval --dry-run
python manage.py memory_file_backed_e2e
python manage.py memory_file_content_search_e2e
python manage.py memory_file_auto_organization_e2e
python manage.py memory_reindex --corpus all --backend fulltext --dry-run
python manage.py memory_reindex --corpus all --backend vector --dry-run
python manage.py source_adapter_reconcile --source-code workorders --target all --backend fulltext --dry-run
python manage.py source_adapter_reconcile --source-code waiting_list --target all --backend fulltext --dry-run
```

Документация, backlog и workflow должны отличать эту рабочую границу от будущих этапов fragment search, graph runtime search, OCR, claim/belief и MLflow.
