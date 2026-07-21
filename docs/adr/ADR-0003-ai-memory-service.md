# ADR-0003: AI Memory Service Architecture

## Status

Accepted

## Date

2026-05-19

## Context

The project needs an AI memory block ("СоСНА") that can combine organizational knowledge, user/session context, integration snapshots, work orders, inventory data, contracts, and selected medical knowledge. The memory block must support graph retrieval from the first implementation stage, while still preserving the project's existing constraints:

- Django remains the system of record for business data, identity, policies, and audit.
- Agent runtime must use declared tools and must not write directly to operational databases or indexes.
- Default contracts live in `contracts/`; runtime editable contracts live in `data/contracts/`.
- Mutable data and generated indexes live under `data/`, not in the repository root.
- Patient data can enter the memory block only after de-identification or stable ID/pseudonym replacement.
- LLM mode is mixed: local by default, optional cloud only after sensitivity routing.
- PostgreSQL is possible later, but the MVP should not require it without proven need.

The detailed implementation roadmap is documented in `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md`.

## Decision

Implement СоСНА as a governance-first memory core owned by this project, with replaceable adapters for storage and OSS memory frameworks.

The accepted baseline is:

- create a dedicated Django app `apps.memory` for memory metadata, policies, ingestion orchestration, retrieval orchestration, admin visibility, and audit;
- store raw immutable snapshots and safe de-identified corpora under `data/memory/`;
- define memory sources, profiles, and routing in JSON contracts under `contracts/ai/`, copied at runtime to `data/contracts/ai/`;
- use Kuzu as the first embedded graph backend;
- use LanceDB or Qdrant as the vector/full-text retrieval backend after a short spike, with LanceDB preferred for an embedded MVP and Qdrant preferred if service isolation or stronger production vector operations become necessary;
- use local embedding models first, with `BAAI/bge-m3` and `intfloat/multilingual-e5-large` as initial candidates for Russian/multilingual retrieval evaluation;
- use Presidio plus project-specific recognizers and deterministic pseudonymization for de-identification;
- use a `memory.search` declared AI tool as the only runtime access path from the agent to memory;
- apply RBAC/scope filtering in the retrieval backend and repeat filtering in Django before assembling context;
- use local LLMs by default for sensitive retrieval, graph extraction, and PII checks;
- permit cloud LLM calls only through an explicit sensitivity route gate;
- treat Graphiti, Cognee, LightRAG, and Mem0 as optional spike/adapters, not as authoritative owners of project memory contracts or governance.

## Alternatives Considered

### Cognee as the primary memory framework

Cognee provides a configurable framework for LLMs, embeddings, vector stores, graph stores, relational metadata, permissions, and local setup. It could accelerate a prototype.

Rejected as primary core because the project needs strict control over contracts, RBAC, PII handling, audit, raw/safe corpus separation, and local/cloud routing. Using Cognee as the owner of the memory lifecycle would create avoidable lock-in and could make security review harder.

### Graphiti as the primary memory framework

Graphiti matches several requirements well: temporal context graphs, provenance, incremental updates, hybrid retrieval, and graph-first agent memory.

Not accepted as primary core yet because it still requires surrounding governance, user/session management, policy enforcement, audit, routing, and project-specific de-identification. It remains a strong candidate for a `GraphMemoryBackend` adapter after a focused spike.

### LightRAG as the primary memory framework

LightRAG is useful as an end-to-end GraphRAG/RAG framework and benchmark candidate.

Rejected as primary core because it is closer to a standalone RAG product than to a policy-first component inside the existing Django monorepo.

### Mem0 as the primary memory framework

Mem0 is useful for per-user agent memory and self-hosted memory APIs.

Rejected as primary core because СоСНА must cover organizational knowledge, business objects, contracts, integration snapshots, graph relations, citations, and strict scope-based access rather than only personal memory.

### PostgreSQL + pgvector from day one

PostgreSQL could centralize metadata, vector search, and operational reporting.

Deferred because the current project can proceed with SQLite/Django metadata and embedded indexes. PostgreSQL remains an evolution path if concurrency, reporting, pgvector, or deployment needs justify the operational cost.

## Consequences

### Positive

- The memory block follows existing repository rules: contracts in `contracts/`, runtime state in `data/`, and business access through Django policies.
- Graphs are included from the first implementation stage without making the whole system dependent on one GraphRAG framework.
- Patient data handling is explicit and testable before any LLM call.
- Retrieval can mix graph, vector, and full-text results while still returning citations and audit traces.
- Storage backends remain replaceable through adapters.
- Cloud LLM usage is controlled by a policy gate rather than by prompt instructions.

### Negative

- More implementation work is required than adopting a single framework.
- The project must own retrieval orchestration, rank fusion, evaluation, and admin observability.
- Graph extraction quality must be tested and improved for Russian medical/business data.
- Embedded storage is simpler operationally but may need migration if data volume or concurrency grows.

### Required Follow-up

- Add `apps.memory` only after contracts and spikes are complete.
- Add `contracts/ai/memory_sources.json`, `memory_profiles.json`, and `memory_routing.json` with schemas and validators.
- Run a Graphiti/Kuzu/local-LLM spike before deciding whether Graphiti is used as an adapter.
- Run an embedding/vector backend spike before finalizing LanceDB vs Qdrant.
- Add security evaluation suites for PII leakage, secret leakage, forbidden-scope leakage, and cloud-routing denial.

