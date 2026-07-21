# Task Acceptance: memory hybrid ranking profiles

## Accepted

- `memory.search` принимает `ranking_profile` и возвращает выбранный профиль в `meta`.
- Профили ранжирования используют RRF, а не прямое сложение raw BM25/vector score.
- Source semantic search работает для `source_data` через `source_explicit` + `source_semantic`.
- ИИ-бот получает подсказки, когда выбирать `source_content`, `source_semantic`, `semantic_heavy`, `precise` и `balanced`.
- Документы с секретами не попадают в FTS/vector и создают blocker issue.
- Документы с PII индексируются и создают audit issue `pii_audit`.
- Reindex удаляет индексы пропавших source-документов и переиндексирует документы при изменении ACL/sensitivity/trust/version.
- Текущая гранулярность явно зафиксирована как временный document-level индекс.

## Evidence

- Unit/integration: `apps.memory.tests` — 45 passed.
- Unit/integration: `apps.ai.tests` — 56 passed.
- Agent runtime unit: 5 passed.
- E2E: `memory_file_content_search_e2e` — succeeded, 6 documents.
- Manual runtime e2e: `source_semantic` profile returned `source_data` with vector channel requested.

## Residual Work

- Фрагментный индекс через `MemorySearchSegment`.
- Reranking как planned/optional на отдельном vector-срезе.
- Graph runtime search для профиля `graph_future`.
