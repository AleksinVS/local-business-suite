# Executor Report: task-memory-backend-spikes

Block: `block-ai-memory-service-2026-05-19`

Slice: `slice-backend-spikes`

Task: `task-memory-backend-spikes`

Status: completed

## Scope

Completed bounded architecture spikes for graph and vector/full-text backends. This task did not modify production code, dependencies, or contracts.

## Subagents

- Vector/full-text spike worker: compared LanceDB and Qdrant.
- Graph spike worker: compared Kuzu-first own graph extractor and Graphiti adapter.
- Orchestrator integration: reviewed both local `.local/` reports and recorded the accepted recommendations in this workflow report.

## Local Spike Artifacts

The detailed local reports are intentionally stored in `.local/` and are not committed:

- `.local/memory-spike-vector-2026-05-19.md`
- `.local/memory-spike-graph-2026-05-19.md`

## Recommendation

Use the following backend direction for the first production implementation:

- vector backend: **LanceDB-first** under `data/memory/indexes/lancedb/`;
- full-text backend: **SQLite FTS / project-side full-text profile** for MVP, with retrieval fusion in Django;
- graph backend: **Kuzu-first own graph extractor** under `data/memory/indexes/kuzu/`;
- Graphiti: keep as a second-phase adapter spike after memory contracts, safe corpus, scope tokens, and Kuzu baseline exist;
- Qdrant: keep as migration target if service isolation, high concurrency, stricter vector operations, snapshots/restore, or advanced dense/sparse production search become necessary.

## Rationale

LanceDB fits the first local-first implementation because it is embedded, requires no separate daemon, maps cleanly to `data/memory/indexes/lancedb/`, and is easy to test with temporary directories. Qdrant has a stronger long-term service and payload-filtering model, but adds operational surface before it is needed.

Kuzu-first graph implementation fits ADR-0003 because it keeps graph state embedded under `data/memory/indexes/kuzu/` and lets Django remain the authority for metadata, policy, audit, and provenance. Graphiti is attractive for temporal/provenance-rich agent memory, but it adds Neo4j/FalkorDB, LLM/schema reliability risks, and a larger operational footprint for the first MVP.

## Design Constraints for Follow-up Tasks

- Keep backend interfaces narrow and replaceable:
  - `VectorMemoryBackend`
  - `GraphMemoryBackend`
- Treat backend filtering as a candidate filter only; Django post-filtering remains mandatory.
- Rebuild indexes from safe corpus and Django metadata rather than binary-converting backend internals.
- Store generated indexes only under `data/memory/indexes/`.
- Do not make backend imports mandatory at Django startup until dependencies are accepted and installed.
- Do not let graph/vector stores become source of truth for RBAC, audit, or contract state.

## Verification

| Check | Result |
| --- | --- |
| Vector/full-text spike report written to `.local/memory-spike-vector-2026-05-19.md` | PASS |
| Graph spike report written to `.local/memory-spike-graph-2026-05-19.md` | PASS |
| Production code unchanged by spike workers | PASS |
| Dependencies unchanged by spike workers | PASS |
| Contracts unchanged by spike workers | PASS |

## Deferred

- No backend packages installed yet.
- No runtime benchmark was executed.
- No `apps.memory` implementation yet.
- No Graphiti adapter implementation yet.

