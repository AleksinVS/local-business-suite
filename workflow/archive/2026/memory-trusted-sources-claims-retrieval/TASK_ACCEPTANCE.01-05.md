# Task acceptance: trusted sources, claims and lightweight retrieval

Дата: 2026-05-21.

## Acceptance

- Контракты доверия, claim/belief и бюджета retrieval валидируются командой `validate_architecture_contracts`.
- `memory.search` не возвращает `candidate_only`, `quarantined` и `blocked` источники в обычном trusted-only режиме.
- Accepted beliefs доступны как отдельный тип контекста `memory_belief`.
- Candidate/contested/expired beliefs не входят в обычный контекст.
- Retrieval trace фиксирует trust-gate и context-packing решения.
- Hot path не вызывает LLM; `memory_eval` проверяет это контрактом.
- Prompt-injection fixture в untrusted source не возвращается через agent tool `memory.search`.

## Verification

Выполнены до приемки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python -m json.tool contracts/ai/memory_trust_policy.json
python -m json.tool contracts/ai/memory_claims_policy.json
python -m json.tool contracts/ai/memory_retrieval_budget.json
```

Полный набор тестов указан в финальном отчете исполнения текущего turn.
