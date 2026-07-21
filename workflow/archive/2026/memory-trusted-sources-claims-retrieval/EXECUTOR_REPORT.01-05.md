# Executor report: trusted sources, claims and lightweight retrieval

Дата: 2026-05-21.

## Выполнено

- Добавлены контракты `memory_trust_policy.json`, `memory_claims_policy.json`, `memory_retrieval_budget.json` и схемы для них.
- Расширен `MemorySource`: `trust_status`, `authority_class`, `trusted_for_context`, `requires_source_review`, `review_owner`, `trusted_context_kinds`, `untrusted_handling`.
- `memory.search` по умолчанию использует trusted-only gate для chunks и graph facts.
- В citations и metadata выдачи добавлены `trust_status`, `authority_class`, `trusted_for_context`.
- Добавлены модели `MemoryClaim` и `MemoryBelief` с lifecycle-статусами, evidence, scope, sensitivity, review metadata и admin-регистрацией.
- Explicit chat memory создает accepted claim и accepted belief после обработки queued request.
- Retrieval orchestration собирает chunks, graph facts и accepted beliefs, затем применяет детерминированное ранжирование и context packing без LLM.
- `memory_reflect_chats` показывает количество accepted belief digest items в deterministic-only режиме.
- `memory_eval` расширен проверками trusted-source defaults и отсутствия обязательного LLM в hot path.
- Добавлены regression tests для trust gate, accepted beliefs и prompt-injection текста в untrusted source.

## Измененные области

- `contracts/ai/`, `contracts/schemas/`
- `config/settings.py`
- `apps/core/json_utils.py`
- `apps/core/management/commands/validate_architecture_contracts.py`
- `apps/memory/models.py`, `admin.py`, `policies.py`, `services.py`, `retrieval.py`, `chat_memory.py`
- `apps/memory/management/commands/memory_reflect_chats.py`, `memory_eval.py`
- `apps/memory/tests.py`, `apps/ai/tests.py`
- `docs/guides/`, `docs/deployment/`, `workflow/active/`

## Ограничения первого среза

- Review UI остается на уровне Django Admin.
- Claim extraction из внешних источников остается фоновым следующим этапом; текущий срез создает claims для explicit chat memory и дает модель для candidates.
- Optional LLM rerank описан контрактом, но отключен и не используется.
- Отдельная таблица `MemoryRetrievalTrace` не вводилась: trace остается в `MemoryAccessAudit.retrieval_trace`.
