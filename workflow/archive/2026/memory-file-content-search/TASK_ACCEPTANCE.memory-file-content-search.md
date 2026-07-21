# Acceptance: memory file content search

Дата: 2026-05-26.

## Проверки

- `python manage.py check` — passed.
- `python manage.py validate_architecture_contracts` — passed.
- `python manage.py memory_reindex --corpus all --backend fulltext --dry-run` — passed.
- `python manage.py memory_reindex --corpus all --backend vector --dry-run` — passed.
- `python manage.py memory_file_content_search_e2e` — passed.
- `python manage.py test apps.memory.tests apps.ai.tests` — passed, 99 tests.

## Приемка

- `.txt/.md/.csv/.tsv/.xlsx/.xls` находились по словам, присутствующим только в содержимом файла.
- `.xls` fixture прочитан через `python-calamine`.
- `source_data` результат возвращается с warning.
- Prefix fallback отражен в `MemoryAccessAudit.retrieval_trace`.
- Полный извлеченный текст не попадает в `MemorySearchDocument.metadata`.
- FTS/vector reindex dry-run работает по корпусам и backend.
