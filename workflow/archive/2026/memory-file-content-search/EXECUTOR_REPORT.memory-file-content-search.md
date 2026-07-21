# Executor report: memory file content search

Дата: 2026-05-26.

## Выполнено

- Реализован `apps.memory.source_text_extraction` для `.txt/.md/.log/.json/.yaml/.yml/.csv/.tsv/.xlsx/.xls`.
- `.xls/.xlsx` читаются через `python-calamine`; макросы не исполняются, формулы не пересчитываются.
- `SQLiteFTSMemoryBackend` переведен на FTS5 с contentless delete table, token fallback и prefix fallback.
- Добавлен `apps.memory.embeddings` с deterministic local test provider и optional SentenceTransformers provider.
- Добавлен LanceDB vector backend в `data/indexes/vector/lancedb/`.
- Индексация knowledge/source_data пишет FTS и vector records без полного текста в `MemorySearchDocument.metadata`.
- `memory.search` объединяет fulltext и vector candidates; `knowledge_semantic` запрашивает vector backend.
- `memory_reindex` поддерживает `--corpus`, `--backend`, `--source-code`, `--dry-run`, `--force`.
- Добавлена команда `memory_file_content_search_e2e`.
- Обновлены контракты, зависимости, README, architecture/current-state, guides и planning/backlog.

## Ограничения

- MVP возвращает документ целиком, не раздел/фрагмент.
- Production multilingual embedding model не устанавливается автоматически; профиль подключается настройкой после подготовки модели.
- Reranking остался optional/planned и выключен.
- OCR, PDF/DOC/DOCX parsers и graph runtime search не включены.
