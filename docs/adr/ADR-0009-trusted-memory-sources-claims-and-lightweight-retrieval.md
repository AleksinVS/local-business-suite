# ADR-0009: Trusted memory sources, claim/belief layer and lightweight retrieval orchestration

## Status

Accepted

MVP boundary adjusted by `docs/adr/ADR-0010-memory-mvp-simplification.md`: `MemoryBelief` is deferred beyond MVP, while trusted-source gates and lightweight retrieval remain accepted.

## Date

2026-05-21

## Context

ADR-0003 accepted a governance-first memory service with raw/safe corpus separation, RBAC, audit and replaceable retrieval backends. ADR-0005 added chat-derived memory, sleep-time reflection and secret handles. ADR-0006 and ADR-0008 expanded ingestion to external systems, email and knowledge-driven analytics.

The next memory architecture concern is trust and local runtime cost:

- not every ingested source should be eligible for direct agent context;
- untrusted or unaudited sources can contain prompt injection, stale claims, low-quality facts, contradictions or source-specific bias;
- organization knowledge must not become shared memory merely because a document, email or API record was discovered;
- the system needs a claim/belief layer so retrieved evidence can be compared, contradicted, superseded and reviewed instead of blindly treated as truth;
- retrieval orchestration must remain cheap enough for a weak local LLM running on consumer hardware.

External references considered:

- OpenClaw memory and memory-wiki patterns: active memory, dreaming, structured claims, evidence, contradictions, open questions and compiled digests: https://docs.openclaw.ai/concepts/memory and https://docs.openclaw.ai/plugins/memory-wiki
- Hermes persistent memory pattern: bounded `MEMORY.md` / `USER.md`, frozen prompt snapshot and searchable session archive: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/memory.md
- LangGraph memory categories: semantic, episodic and procedural memory, with hot-path versus background updates: https://langchain-ai.github.io/langgraph/concepts/memory/
- OWASP LLM Prompt Injection guidance: RAG does not eliminate prompt injection; retrieved content must be treated as data, not instructions: https://genai.owasp.org/llmrisk/llm01-prompt-injection/

## Decision

Extend the memory architecture with three governed layers:

1. trusted source policy;
2. claim/belief memory layer;
3. lightweight retrieval orchestration budget.

### Trusted Source Policy

Add a first-class trusted-source concept to memory source governance.

Every memory source must have an effective trust status:

- `trusted`: eligible for direct agent context after scope, sensitivity and citation checks;
- `candidate_only`: may be ingested, parsed and used to create source/claim candidates, but must not be assembled into agent context until approved;
- `quarantined`: may be retained for security/debug/audit according to retention policy, but not used for candidate extraction unless explicitly reviewed;
- `blocked`: must not be ingested or searched.

Direct runtime `memory.search` context assembly must use only trusted sources by default. Untrusted sources can still be processed into candidates, but those candidates require audit by the source owner, knowledge owner or graph owner before publication into trusted organization memory.

Personal chat memory is trusted only within its personal scope and only for user-owned facts/preferences/procedures. A user statement is not automatically trusted as organization knowledge. External emails, documents and APIs are not automatically trusted merely because the transport was authenticated.

### Claim/Belief Layer

Add a claim/belief layer above safe corpus, chunks and graph facts.

A `claim` is an atomic assertion extracted from a trusted or candidate source, with provenance, evidence, scope, sensitivity, time validity, confidence and status. A claim can be accepted, rejected, superseded, contested or left as candidate.

A `belief` is the system's current governed view computed from one or more claims. It is not "absolute truth"; it is the best accepted operational position for a scope and time window, with supporting and contradicting evidence.

The claim/belief layer must support:

- provenance-rich claims with source/chunk/message/email/object references;
- contradiction detection and contested status;
- freshness and validity windows;
- rejected claims as negative examples;
- human review for organization-level beliefs;
- compiled low-token digests for runtime agent context.

### Lightweight Retrieval Orchestration

The local LLM must not be the default executor for retrieval orchestration. Retrieval should be deterministic and budgeted first, with LLM use limited to narrow, optional, low-frequency tasks.

Default runtime path:

1. deterministic source trust gate;
2. scope/sensitivity gate;
3. full-text/vector/graph candidate retrieval;
4. cheap rank fusion and freshness scoring;
5. deterministic citation/context packing;
6. optional small local LLM pass only after the candidate set is tiny and only when the route allows it.

Background jobs may use the local LLM for claim extraction, contradiction summaries or digest generation only under explicit budgets, batching, caching and off-peak scheduling. Heavy extraction remains an offline/reflection concern, not a per-request requirement.

## Alternatives Considered

### Trust all ingested safe corpus after DLP

Rejected. Safe corpus means content passed privacy/security cleaning; it does not mean the source is authoritative or free from prompt-injection instructions, stale facts or contradictions.

### Let the LLM judge source trust at retrieval time

Rejected. Source trust is a policy decision, not a prompt decision. The LLM can assist candidate explanation, but cannot be the authority that decides whether a source is trusted.

### Store only final beliefs and discard claims

Rejected. Without claims and evidence, the system cannot audit how a belief was formed, explain contradictions, preserve rejected examples, or update beliefs when sources become stale.

### Use LLM reranking for every retrieval request

Rejected for MVP. The target runtime includes weak local models on consumer hardware. Per-request LLM reranking would increase latency, cost and instability. Deterministic scoring is the baseline; LLM reranking is a later optional optimization.

## Consequences

### Positive

- Untrusted sources can be collected without becoming direct agent instructions.
- Memory poisoning and indirect prompt injection risks are reduced by policy gates before context assembly.
- Organization knowledge can express disagreement, uncertainty and source provenance.
- Local runtime remains usable on modest hardware.
- The architecture can still evolve toward stronger LLM extraction/reranking later.

### Negative

- More contract fields, review queues and admin states are required.
- Some useful new source data will wait for audit before the agent can use it directly.
- Claim/belief extraction and contradiction detection need careful evaluation.
- Retrieval orchestration becomes more explicit and must be monitored with latency and token budgets.

## Required Follow-up

- Add trust policy fields to memory source contracts and validators.
- Add source trust gates to retrieval and context assembly.
- Add source/claim candidate review workflow.
- Add claim/belief models or equivalent tables with provenance and status.
- Add lightweight rank-fusion/context-packing service that does not require LLM calls.
- Add tests proving untrusted sources are not returned to the agent as direct context.
- Add security eval cases for prompt-injection and memory-poisoning attempts.
