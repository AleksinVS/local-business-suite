# Executor Report: task-memory-indexing

Block: `block-ai-memory-service-2026-05-19`

Slice: `slice-indexing`

Task: `task-memory-indexing`

Status: completed

## Scope

Implemented replaceable indexing interfaces and MVP local backends for the СоСНА memory service. The slice indexes only privacy-processed safe text, keeps generated index files under `data/memory/indexes/`, stores manifests under `data/memory/manifests/`, and preserves Django as the authority for provenance, scope, sensitivity, and audit metadata.

## Subagents

- Vector/full-text backend worker: implemented `SQLiteFTSMemoryBackend` with FTS5 and LIKE fallback.
- Graph backend worker: implemented `DjangoGraphMemoryBackend` and lazy `KuzuGraphMemoryBackend` placeholder.
- Orchestrator integration: implemented safe-text ingestion, backend adapter calls, manifest/safe-corpus writers, services, tests, and acceptance.

## Changed Files

- `apps/memory/vector_backends.py`
- `apps/memory/graph_backends.py`
- `apps/memory/ingestion.py`
- `apps/memory/services.py`
- `apps/memory/tests.py`
- `apps/memory/.desc.json`
- `workflow/active/block-ai-memory-service-2026-05-19/.desc.json`
- `PROJECT_STRUCTURE.yaml`

## Implementation Notes

- `SQLiteFTSMemoryBackend` is embedded and dependency-free, with indexes at `data/memory/indexes/sqlite_fts/memory_fts.sqlite3` by default.
- `MemoryIndexRecord` carries chunk text, metadata, scope tokens, sensitivity, activity flag, and optional embedding placeholder.
- Vector/full-text search filters active chunks by scope and sensitivity metadata and returns chunk IDs plus backend scores.
- `DjangoGraphMemoryBackend` upserts `MemoryGraphFact` records idempotently by `fact_id`, validates chunk/snapshot provenance, and supports scope/sensitivity-filtered graph search.
- `KuzuGraphMemoryBackend` imports `kuzu` lazily and raises a clear runtime error until the optional adapter is implemented.
- `index_snapshot_text()` writes safe corpus files, upserts chunks, deactivates stale chunks/facts, updates vector/full-text index records, writes graph facts, and writes a manifest.
- `chunk_id` is stable by snapshot and position; `text_hash` remains separate so reindexing the same snapshot updates a chunk instead of conflicting with `(snapshot, position)`.

## Verification

| Check | Result |
| --- | --- |
| `./.venv/bin/python -m py_compile apps/memory/ingestion.py apps/memory/vector_backends.py apps/memory/graph_backends.py` | PASS |
| `./.venv/bin/python manage.py test apps.memory.tests` | PASS, 17 tests |
| `./.venv/bin/python manage.py check` | PASS |
| `./.venv/bin/python manage.py validate_architecture_contracts` | PASS |
| `./.venv/bin/python manage.py test apps.core.tests apps.memory.tests` | PASS, 34 tests |

## Deferred

- No LanceDB, Kuzu, Qdrant, or Graphiti package was added in this slice; the dependency surface remains unchanged.
- The local graph extractor is intentionally minimal and pattern-based; richer extraction belongs in a later source-adapter/extractor slice.
- Vector embeddings are represented in the interface but not generated yet.
- Retrieval fusion and `memory.search` tool implementation remain in `task-memory-retrieval-tool`.
