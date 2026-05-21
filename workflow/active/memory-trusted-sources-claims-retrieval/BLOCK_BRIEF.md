# Block brief: memory trusted sources, claims and lightweight retrieval

## Goal

Implement a governed memory upgrade where only trusted sources can feed normal agent context, untrusted sources create candidates for audit, accepted claims compile into beliefs, and retrieval orchestration remains cheap for a weak local LLM.

## Architecture Sources

- `docs/adr/ADR-0003-ai-memory-service.md`
- `docs/adr/ADR-0005-chat-derived-memory-and-secret-handles.md`
- `docs/adr/ADR-0006-external-system-knowledge-connectors.md`
- `docs/adr/ADR-0008-knowledge-driven-business-analytics.md`
- `docs/adr/ADR-0009-trusted-memory-sources-claims-and-lightweight-retrieval.md`
- `docs/architecture/MEMORY_TRUSTED_SOURCES_CLAIMS_AND_RETRIEVAL_PLAN.md`
- `docs/planning/active/memory-trusted-sources-claims-retrieval.md`

## Scope

- memory trust contracts and validators;
- retrieval trusted-source gate;
- source/claim candidate review states;
- claim/belief data model and admin visibility;
- deterministic retrieval rank fusion and context packing;
- off-peak digest/reflection extensions;
- security and latency tests.

## Non-goals

- no new external memory framework as authority;
- no mandatory LLM reranking;
- no direct use of untrusted source data in agent context;
- no secret value handling changes beyond preserving existing no-value rule;
- no production-specific connector implementation in this block.

## Constraints

- Django remains the authority for policy, audit and metadata.
- Runtime data stays under `data/`.
- Contracts live under `contracts/`, runtime copies under `data/contracts/`.
- Source trust is enforced by code, not prompt wording.
- Candidate-only content may be stored and reviewed but not assembled into normal answers.
- Local LLM calls must be optional, bounded and disabled by default in hot path.

## Done Criteria

- Trust policy fields are validated.
- Untrusted/candidate/quarantined sources are filtered from normal `memory.search` results.
- Claim/belief lifecycle supports accepted, rejected, contested, superseded and expired states.
- Accepted beliefs include evidence and citation provenance.
- Retrieval hot path works without LLM calls and records budget/trace metadata.
- Tests cover source trust, claim review, poisoning fixtures and latency budget smoke.
