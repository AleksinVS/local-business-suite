# Task Acceptance: task-memory-indexing

Block: `block-ai-memory-service-2026-05-19`

Task: `task-memory-indexing`

Decision: accepted

## Acceptance Review

The task satisfies the declared scope:

- Graph and vector/full-text backend interfaces exist.
- MVP embedded full-text backend writes generated indexes under `data/memory/indexes/`.
- Graph facts and chunks are linked to `MemorySnapshot` and safe `MemoryChunk` provenance.
- Chunk and graph upserts are idempotent.
- Reindexing deactivates stale chunks and stale graph facts without deleting snapshots.
- Scope and sensitivity metadata are preserved and filterable in backend search helpers.
- Optional Kuzu support is lazy and does not affect Django startup.
- No raw PII snapshot text is indexed by the ingestion service.

## Required Checks

All required checks passed:

- `./.venv/bin/python manage.py test apps.memory.tests`
- `./.venv/bin/python manage.py check`
- `./.venv/bin/python manage.py validate_architecture_contracts`

Additional checks passed:

- `./.venv/bin/python -m py_compile apps/memory/ingestion.py apps/memory/vector_backends.py apps/memory/graph_backends.py`
- `./.venv/bin/python manage.py test apps.core.tests apps.memory.tests`

## Notes

The next implementation candidate is `task-memory-retrieval-tool`. It should treat backend search results as candidates only and apply Django-side policy checks, rank fusion, citations, and `MemoryAccessAudit` before returning anything to agent runtime.
