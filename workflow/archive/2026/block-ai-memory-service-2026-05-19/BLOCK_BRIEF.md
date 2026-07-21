# Summary

- goal: Implement the СоСНА AI memory service as a governance-first Django memory block with contracts, raw/safe corpus, graph/vector/full-text retrieval, RBAC filtering, PII protection, and a declared `memory.search` tool.
- scope: planning and implementation are governed by `docs/adr/ADR-0003-ai-memory-service.md`, `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md`, and `docs/planning/active/ai-memory-service.md`.
- changes: Add memory contracts and validators, then add `apps.memory`, ingestion/privacy/index/retrieval layers, management commands, tests, and admin observability.
- non-goals: Do not migrate to PostgreSQL, do not add a separate `services/memory_runtime` in the first block, do not connect production Bitrix24/MIS/telephony integrations, and do not allow cloud LLM routing for sensitive context.
- verification: Run `make check`, `make test`, `make contracts`, memory-specific management command smoke checks, and security evaluation suites before block acceptance.

