# Workflow brief: memory file content search

## Goal

Implement file-content search for memory documents according to ADR-0015 and the active plan.

## Read Scope

- `docs/adr/ADR-0015-file-content-fts-vector-search.md`;
- `docs/planning/active/memory-file-content-fts-and-vector-search.md`;
- `apps/memory/`;
- `apps/ai/`;
- `apps/core/`;
- `contracts/ai/`;
- `contracts/schemas/`;
- `docs/architecture/`;
- `docs/guides/`;
- `requirements.txt`;
- `requirements.lock`.

## Write Scope

- memory extraction, indexing, retrieval and management commands under `apps/memory/`;
- AI memory search contracts and tests when payload or trace behavior changes;
- memory profiles and schemas when backend/profile status changes;
- docs, backlog, workflow reports and generated project structure files;
- dependency manifests if a runtime dependency is added.

Runtime indexes stay under `data/indexes/`. Temporary experiments and logs stay under `.local/`.

## Non-goals

- No OCR/image recognition.
- No PDF/DOC/DOCX production parser.
- No graph runtime search.
- No cloud embeddings for file content.
- No fragment/segment result model in this implementation slice.

## Acceptance

- Text extraction covers text and tabular MVP formats, including `.xls` and `.xlsx`.
- SQLite FTS5 is used when available, with token fallback and prefix fallback trace.
- `memory_reindex` supports corpus/backend/source/dry-run/force.
- LanceDB vector backend and local embedding providers are implemented.
- `memory.search` can use precise, semantic, explicit source and fallback modes.
- E2E command validates file-content search without storing full extracted text in `MemorySearchDocument.metadata`.
