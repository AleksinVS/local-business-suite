# Handoff Report: memory-file-backed-knowledge

Дата: 2026-05-22.

## Срезы

- `01-knowledge-file-format-and-writer` - выполнено.
- `02-reader-service-and-metadata-db` - выполнено в MVP-границе: metadata поля добавлены, проверка чтения подключена через права chunks/knowledge.
- `03-unified-search-index-service` - выполнено в MVP-границе: общий SQLite FTS path, режимы поиска, `knowledge` results, source-data fallback по безопасным metadata.
- `04-source-data-temporary-processing` - выполнено частично: добавлены processing paths и cleanup command; legacy safe corpus оставлен для старого ingestion.
- `05-chat-and-analytics-db-split` - выполнено: добавлены aliases, router и legacy-copy команды.
- `06-reflection-and-migration-hardening` - выполнено в MVP-границе: writer/index/reflection команды разделены, legacy alias сохранен.

## Что реализовано

- `data/knowledge_repo/` как runtime Git-репозиторий знаний.
- Markdown + YAML front matter формат знания.
- Atomic write через temporary file, lock и `os.replace`.
- Git commit на изменение знания.
- Новые metadata поля `MemoryKnowledgeItem`.
- Отдельные базы `chat`, `knowledge_meta`, `analytics_control`.
- Команды:
  - `knowledge_writer_worker`;
  - `knowledge_index_worker`;
  - `knowledge_reflection_worker`;
  - `memory_export_knowledge_files`;
  - `memory_verify_knowledge_files`;
  - `memory_migrate_legacy_knowledge`;
  - `migrate_legacy_chat_db`;
  - `migrate_legacy_analytics_control_db`;
  - `memory_processing_cleanup`;
  - `memory_file_backed_e2e`.
- `memory_reflect_chats` оставлен как совместимый alias только для очереди записи.

## Проверки

Выполнено во время реализации:

- `python manage.py check` - OK.
- `python manage.py test apps.memory.tests.MemoryChatKnowledgeTests` - OK.
- `python manage.py test apps.ai.tests.IdentityContextPropagationTests.test_memory_remember_tool_queues_request_without_secret_value_in_audit apps.ai.tests.IdentityContextPropagationTests.test_memory_search_tool_returns_citations_and_task_type_report` - OK.
- `python manage.py test apps.analytics.tests.KnowledgeDrivenAnalyticsTests.test_email_fixture_sync_extracts_business_facts_and_metrics` - OK.
- `python manage.py test apps.memory.tests apps.ai.tests apps.analytics.tests` - 110 tests OK.
- `python manage.py test apps.memory.tests.MemoryIndexingPipelineTests.test_memory_search_falls_back_to_source_data_metadata_when_knowledge_empty` - OK.
- `python manage.py validate_architecture_contracts` - OK.
- `python manage.py makemigrations --check --dry-run` - OK.
- `python manage.py memory_eval --dry-run` - OK.
- `python manage.py memory_file_backed_e2e` - OK.
- `npm run test:e2e` - 1 Playwright test OK.
- `python manage.py memory_verify_knowledge_files --strict` - OK.
- `git diff --check -- . ':(exclude)BACKLOG.md'` - OK.

## Остаточные риски

- `MemorySnapshot` и `MemoryChunk` сохранены как совместимый слой индексации; отдельный исполнительный блок удаления подготовлен в `workflow/active/memory-snapshot-chunk-removal/`.
- Старые таблицы в `main_vault.sqlite3` не удаляются автоматически.
- DuckDB для аналитических срезов не входит в этот срез.
- Детальная стратегия графового поиска остается отдельной задачей.
