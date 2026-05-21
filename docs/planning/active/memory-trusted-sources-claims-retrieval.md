# Active plan: trusted sources, claims and lightweight retrieval

Статус: первый исполнительский срез реализован; MVP-граница уточнена через `docs/adr/ADR-0010-memory-mvp-simplification.md`.

Дата: 2026-05-21.

## Цель

Усилить систему памяти так, чтобы агент получал runtime context только из надежных источников, а спорные или неаудированные данные проходили через candidates/review. После уточнения MVP `MemoryBelief` переносится на следующие этапы, а главным объектом сохраненного знания становится `MemoryKnowledgeItem`.

## Контекст

Связанные документы:

- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0005-chat-derived-memory-and-secret-handles.md`;
- `docs/adr/ADR-0006-external-system-knowledge-connectors.md`;
- `docs/adr/ADR-0008-knowledge-driven-business-analytics.md`;
- `docs/adr/ADR-0009-trusted-memory-sources-claims-and-lightweight-retrieval.md`;
- `docs/adr/ADR-0010-memory-mvp-simplification.md`;
- `docs/architecture/MEMORY_TRUSTED_SOURCES_CLAIMS_AND_RETRIEVAL_PLAN.md`;
- `docs/architecture/MEMORY_MVP_SIMPLIFICATION_PLAN.md`.

Workflow:

- `workflow/active/memory-trusted-sources-claims-retrieval/`.

## Scope

- Trusted source policy and contract fields.
- Candidate-only handling for unaudited sources.
- Source trust gate in retrieval/context assembly.
- `MemoryClaim` остается необязательным слоем для будущей проверки утверждений.
- `MemoryBelief` переносится за пределы MVP.
- Deterministic rank fusion and context packing.
- Optional local LLM usage only behind budget flags and disabled by default.
- Security eval cases for prompt injection and memory poisoning.

## Non-goals

- Do not replace existing safe corpus, chunks or graph facts.
- Do not make OpenClaw/Hermes/Cognee/Graphiti the authoritative memory owner.
- Do not require a stronger local LLM or GPU.
- Do not implement production UI in the first slice beyond admin visibility.
- Do not make untrusted source content directly retrievable for normal agent answers.

## Implementation Order

1. Contracts and validators for trust, claims and retrieval budget - выполнено.
2. Source trust gate in `memory.search` and context assembly - выполнено.
3. Claim/belief data model and candidate review lifecycle - выполнено в MVP через Django models/admin.
4. Lightweight retrieval rank fusion and context packing - выполнено без обязательного LLM.
5. Reflection/digest compiler using accepted beliefs - выполнен deterministic digest count в reflection command.
6. Security and performance eval - добавлены trust/prompt-injection/budget smoke checks.

## Open Decisions for Implementation

Итоги первого среза:

- `MemoryClaim` и `MemoryBelief` реализованы как Django models.
- Evidence refs в MVP хранятся в JSON fields; нормализованные join tables оставлены на следующий этап.
- Source/claim/belief review в MVP идет через Django Admin.
- Budget defaults зафиксированы в `contracts/ai/memory_retrieval_budget.json`; уточнение после замеров остается неблокирующим.

## Acceptance Checks

- `memory.search` default path excludes `candidate_only`, `quarantined` and `blocked` sources.
- Review/admin path can inspect candidate-only source evidence.
- Accepted beliefs are explainable through supporting claims and citations.
- Contested/rejected claims do not enter normal agent context.
- Retrieval hot path passes without LLM call.
- Budget settings are contract-validated.
- Prompt-injection fixture in an untrusted source is not surfaced as agent instruction.

## Verification Commands

Команды проверки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_eval --dry-run
```
