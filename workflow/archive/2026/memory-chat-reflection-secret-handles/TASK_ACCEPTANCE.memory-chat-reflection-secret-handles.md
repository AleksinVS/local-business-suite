# Acceptance: memory-chat-reflection-secret-handles

Дата: 2026-05-20.

## Acceptance checks

- Explicit remember defaults to personal memory: passed by `MemoryChatKnowledgeTests`.
- Organization remember requires elevated permission: passed by `MemoryChatKnowledgeTests`.
- Queued request creates memory job: passed by `AIViewsTests` / `IdentityContextPropagationTests` coverage.
- Secret span becomes `<SECRET_HANDLE:...>` and non-secret text continues ingestion: passed by `MemoryChatKnowledgeTests`.
- Secret value is absent from AI action audit request payload for `memory.remember`: passed by `apps.ai.tests`.
- Personal memory edit/delete works: passed by `MemoryChatKnowledgeTests`.
- Reflection can create organization candidate from high-importance personal memory: passed by `MemoryChatKnowledgeTests`.
- Contracts validate: passed.
- Full Django test suite passes: passed.

## Accepted for MVP

The implementation satisfies the MVP scope of ADR-0005 for queued chat-derived memory and provider-neutral secret handles with a Vaultwarden-compatible external-link backend.

Remaining production hardening is tracked in `docs/planning/backlog.md` and the active plan.
