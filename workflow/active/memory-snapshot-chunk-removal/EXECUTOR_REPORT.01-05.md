# Executor Report: memory-snapshot-chunk-removal

Дата: 2026-05-22.

## Выполнено

- Добавлена модель `MemorySearchDocument` и миграция `0006_memorysearchdocument`.
- Удалены модели `MemorySnapshot`, `MemoryChunk` и привязанный к ним `MemoryGraphFact` миграцией `0007_remove_memorychunk_snapshot_and_more`.
- Удалены старые поля `snapshot`/`source_chunk` из `MemoryClaim`, `MemoryGraphExtractionRun` и `MemoryGraphReviewItem`.
- `memory.remember` после обработки очереди индексирует `MemoryKnowledgeItem` напрямую через `MemorySearchDocument`.
- Полнотекстовый backend переведен с основного идентификатора `chunk_id` на `document_id`; совместимые свойства оставлены только для старых вызовов тестов и аудита.
- `memory.search` читает знания через файл знания и `MemorySearchDocument`, без `MemorySnapshot` и `MemoryChunk`.
- Fallback по `source_data` работает через `MemorySourceObject` и `MemorySearchDocument`.
- Document ingestion и external connector handoff больше не создают новые `MemorySnapshot`/`MemoryChunk`.
- Django Admin заменил разделы snapshots/chunks на `MemorySearchDocument`.
- Graph backend временно выведен в placeholder до отдельной стратегии графового индекса.
- Обновлены тесты, документация и workflow-статусы.

## Проверки

- `./.venv/bin/python manage.py check` - OK.
- `./.venv/bin/python manage.py makemigrations --check --dry-run` - OK.
- `./.venv/bin/python manage.py validate_architecture_contracts` - OK.
- `./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests apps.analytics.tests --verbosity 1` - 106 tests OK.
- `./.venv/bin/python manage.py memory_eval --dry-run` - OK, passed=6 failed=0.
- `./.venv/bin/python manage.py memory_reindex --dry-run` - OK.
- `./.venv/bin/python manage.py memory_processing_cleanup --dry-run` - OK.
- `./.venv/bin/python manage.py memory_verify_knowledge_files --strict` - OK, checked=2 failed=0.
- `./.venv/bin/python manage.py memory_file_backed_e2e` - OK.
- `npm run test:e2e` - OK, 1 test passed after starting local Django on `127.0.0.1:8001`.
- `git diff --check -- . ':(exclude)BACKLOG.md'` - OK.

## Остаточные ограничения

- Детальная стратегия графового поиска остается отдельной задачей.
- Поля аудита с историческим именем `returned_chunk_ids` пока оставлены для совместимости схемы; фактически туда записываются `document_id`.
