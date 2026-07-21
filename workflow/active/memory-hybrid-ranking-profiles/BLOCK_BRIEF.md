# Workflow brief: memory hybrid ranking profiles

## Goal

Implement explainable hybrid ranking profiles for `memory.search`, source semantic search for indexed files, and agent prompts so the AI bot reliably chooses the right search mode.

## Business Value

Users can ask the bot to search accepted knowledge, source files or semantic memory without knowing backend details. Search results become more stable and auditable because FTS, vector and future graph candidates are fused through named profiles instead of raw score addition.

## Read Scope

- `apps/memory/retrieval.py`
- `apps/memory/vector_backends.py`
- `apps/ai/tool_definitions.py`
- `apps/ai/tooling.py`
- `services/agent_runtime/tools.py`
- `services/agent_runtime/prompting.py`
- `services/agent_runtime/task_types.py`
- `contracts/ai/tools.json`
- `contracts/ai/task_types.json`
- `docs/adr/ADR-0015-file-content-fts-vector-search.md`
- `docs/adr/ADR-0016-memory-hybrid-ranking-profiles.md`
- `docs/planning/active/memory-hybrid-ranking-profiles-and-agent-prompts.md`

## Write Scope For Future Implementation

- Memory retrieval ranking and trace code under `apps/memory/`.
- AI tool contract and gateway plumbing under `apps/ai/`.
- Agent runtime tool wrapper, task contract and prompts under `services/agent_runtime/`.
- Tests under `apps/memory/tests.py`, `apps/ai/tests.py` and `services/agent_runtime/tests/`.
- Documentation under `docs/adr/`, `docs/planning/active/` and `docs/guides/`.

Runtime data belongs under `data/memory/`. Temporary e2e artifacts must stay under `.local/`.

## Non-goals

- Do not implement graph runtime search.
- Do not reintroduce `MemoryChunk`.
- Do not allow the AI bot to pass raw channel weights.
- Do not add a new external search API or cloud embeddings.
- Do not index source files by fragments in this stage; use document-level vectors temporarily.
- Do not store full extracted source text in model metadata.

## Acceptance

- `memory.search` accepts or derives `ranking_profile`.
- Raw BM25/vector scores are not summed directly for final ranking.
- RRF-based fusion is used for MVP profiles.
- Source files are indexed into LanceDB and retrievable through explicit source modes.
- Secret-bearing documents are blocked, reported to admin review and removed from FTS/vector indexes.
- PII-bearing documents are indexed but reported to admin audit.
- Trace shows profile, weights, channel ranks and final score.
- Agent runtime prompts clearly map user intent to `search_mode` and `ranking_profile`.
- E2E tests prove `precise`, `balanced`, `semantic_heavy`, `source_content` and `source_semantic` behavior.
