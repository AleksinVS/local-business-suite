# Текущее состояние MVP памяти

Дата: 2026-05-26.

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
  -> SQLite FTS5 index
  -> optional LanceDB vector index
  -> memory.search
```

Текст принятого знания хранится только в файле знания в `data/knowledge_repo/`. `MemoryKnowledgeItem` хранит метаданные, права, статус, хэши и ссылки на источник. `MemorySearchDocument` является технической карточкой индекса и не является источником истины для текста.

## Что работает

- Очередь `memory.remember` через `MemoryWriteRequest` и `MemoryIndexJob`.
- Персональные и организационные знания из AI-чата.
- Secret handles: секретное значение не пишется в знание, индекс, audit и результат поиска.
- Runtime Git-репозиторий знаний `data/knowledge_repo/`.
- Раздельные runtime-базы `chat`, `knowledge_meta` и `analytics_control`.
- Поиск через `memory.search` по корпусу `knowledge`.
- Явный и fallback-показ `source_data` как ссылок на исходные объекты.
- Trusted-only gate для обычного контекста агента.
- `MemoryAccessAudit` для разрешенных и запрещенных поисков.
- Ingestion MVP для local/UNC источников, текстовых файлов и табличных `.csv/.tsv/.xlsx/.xls` с issue queue.
- SQLite FTS5 по содержимому документов с token fallback и prefix fallback.
- LanceDB vector backend с локальным embedding provider; по умолчанию используется легкий deterministic test profile, production-профиль включается через `LOCAL_BUSINESS_MEMORY_EMBEDDING_PROFILE`.
- Документный индекс: результат поиска возвращает документ, а не раздел/фрагмент.
- Graph schema bootstrapping и extraction-команды как отдельный подготовительный контур.
- Reference implementation внешнего коннектора: envelope, queue, landing zone, retention cleanup и handoff.
- Универсальные source adapters для внутренних модулей: `workorders` и `waiting_list` отдают `SourceObjectEnvelope`.
- `source_adapter_reconcile` строит из envelope проекции `MemorySourceObject`, `MemorySearchDocument`, FTS/vector index и analytics projection.
- Для `adapter_check` источников выдача `source_data` выполняет финальную проверку доступа через доменный адаптер; при отсутствии адаптера результат fail-closed.
- Privacy defaults для source adapters: PII по умолчанию выключено, внешние источники могут явно включать `pii_guarded`; secret scanning всегда включен.
- AI-инструмент `workorders.search` ищет по индексированным заявкам через `memory.search` в режиме `source_explicit`.

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
python manage.py memory_reindex --corpus all --backend fulltext --dry-run
python manage.py memory_reindex --corpus all --backend vector --dry-run
python manage.py source_adapter_reconcile --source-code workorders --target all --backend fulltext --dry-run
python manage.py source_adapter_reconcile --source-code waiting_list --target all --backend fulltext --dry-run
```

Документация, backlog и workflow должны отличать эту рабочую границу от будущих этапов fragment search, graph runtime search, OCR, claim/belief и MLflow.
