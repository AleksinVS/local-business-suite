# План: trusted sources, future claim/belief layer и lightweight retrieval orchestration

Статус: первый исполнительский срез реализован; MVP-граница уточнена ADR-0010.

Дата: 2026-05-21.

Связанный ADR: `docs/adr/ADR-0009-trusted-memory-sources-claims-and-lightweight-retrieval.md`.

Дополнение: MVP-граница упрощена решением `docs/adr/ADR-0010-memory-mvp-simplification.md`. `MemoryBelief` переносится на следующие этапы; `MemoryKnowledgeItem` становится главным объектом сохраненной памяти MVP. После ADR-0015 FTS5 и LanceDB vector retrieval включены для документного индекса; graph runtime search остается отключенным. Фактическая рабочая граница описана в `docs/architecture/MEMORY_MVP_CURRENT_STATE.md`.

## Назначение

Этот документ описывает развитие системы памяти после MVP chat memory, document ingestion, external connectors и knowledge-driven analytics. После ADR-0010 обычный MVP-путь опирается на `MemoryKnowledgeItem`; claim/belief слой остается будущим слоем проверки спорных утверждений. Цель - усилить безопасность и качество памяти без перегрузки локальной LLM:

- агент получает контекст только из надежных источников;
- остальные источники сначала проходят аудит и candidate flow;
- знания MVP хранятся как `MemoryKnowledgeItem`, chunks и graph facts; проверяемые claims/beliefs остаются следующим этапом;
- retrieval orchestration выполняется преимущественно детерминированно и дешево.

## Реализация первого среза

На 2026-05-21 реализовано:

- контракты `memory_trust_policy.json`, `memory_claims_policy.json`, `memory_retrieval_budget.json`;
- поля доверия у `MemorySource`;
- trusted-only gate в `memory.search` для поисковых документов и graph facts;
- citations с `trust_status`, `authority_class`, `trusted_for_context`;
- `MemoryClaim` и `MemoryBelief` вынесены из MVP-схемы; future-stage policy оставлен как контракт будущего слоя;
- обычный explicit chat memory больше не создает `MemoryClaim` и `MemoryBelief`;
- deterministic rank fusion и context packing без LLM в hot path;
- digest обработки очереди считается по активным `MemoryKnowledgeItem`;
- smoke/eval проверки trusted-source defaults и запрета обязательного LLM в hot path.

Вне первого среза остаются production UI для review, нормализованные evidence join tables, полноценное claim extraction из внешних источников и optional LLM rerank.

## Принцип

`safe corpus` отвечает на вопрос "можно ли этот текст хранить/индексировать после privacy gate".

`trusted source` отвечает на другой вопрос: "можно ли этот источник использовать как прямой контекст агента".

Текст может быть safe, но не trusted. Например, письмо от внешнего контрагента после DLP может быть безопасно сохранено, но оно не должно напрямую инструктировать агента или становиться организационным фактом без аудита.

## Trusted Source Policy

### Статусы источника

MVP-значения `trust_status`:

| Статус | Значение |
| --- | --- |
| `trusted` | Источник прошел аудит и может попадать в `memory.search` context после RBAC/sensitivity/citation gates. |
| `review_required` | Источник можно ingest-ить и использовать для candidates, но нельзя напрямую отдавать агенту до проверки. |
| `blocked` | Источник не ingest-ится и не ищется. |

Совместимость: старые `candidate_only` и `quarantined` отображаются в `review_required`, `trusted` и `blocked` сохраняют смысл.

### Классы надежности

`trusted` не должен быть одним бинарным флагом без контекста. Нужен `authority_class`:

- `system_of_record` - бизнес-система-источник истины, например утвержденный registry или доменная БД;
- `approved_corpus` - утвержденный корпоративный корпус документов;
- `approved_user_memory` - персональная память владельца в пределах личного scope;
- `reviewed_org_knowledge` - принятые организационные знания; claim/belief слой для этого будет уточнен позже;
- `external_observation` - внешние письма/API/отчеты, даже после аудита остаются наблюдениями, а не приказами;
- `candidate_input` - материал для анализа, но не прямой context.

### Политика по типам источников

| Источник | Default trust |
| --- | --- |
| Chat explicit remember: personal | `trusted` только для `user:<id>` после secret/prompt-injection gate. |
| Chat queue candidate promotion | `review_required` до review владельца знаний. |
| Organization direct remember от пользователя с правом | `trusted` после write permission и security gate; рекомендуется audit trail. |
| Dedicated approved document folder | `review_required` до source audit; затем `trusted` как `approved_corpus`. |
| Email IMAP | `review_required` по умолчанию; trusted только для утвержденных mailbox/folder/rules. |
| External API connector | `review_required` по умолчанию; trusted после ручного source mapping и audit. |
| Analytics-derived facts | `review_required` до принятия metric/playbook owner или knowledge owner. |

### Candidate flow

```text
Discovered / ingested source
  -> privacy/security gate
  -> source trust classifier
  -> review_required landing zone
  -> source owner audit
  -> future claim extraction candidates
  -> knowledge review; future claim/belief review if organization-wide
  -> trusted memory publication
  -> direct agent context eligibility
```

Review может проходить на двух уровнях:

- source-level: можно ли доверять источнику/папке/mailbox/API как классу;
- claim-level: можно ли принять конкретное утверждение как organization belief.

## Future Claim/Belief Layer

ADR-0010 и ADR-0013 переносят этот слой за пределы готового MVP. `MemoryClaim` и `MemoryBelief` не входят в текущую MVP-схему; обычный `memory.remember` их не создает, а обычный `memory.search` их не возвращает.

### Что такое claim

`Claim` - будущий объект для атомарного утверждения, извлеченного из чата, письма, документа, API, аналитики или графа.

Примеры:

- "Отчет заведующего отделением X должен приходить еженедельно по пятницам."
- "Поставщик Y задержал поставку ЗИП по заявке Z."
- "Манго Офис передает записи звонков через API integration profile A."
- "Пользователь Иван предпочитает краткие ответы без лишней теории."

У claim есть:

- тип: `fact`, `preference`, `procedure`, `policy`, `decision`, `metric_observation`, `incident`, `action_outcome`;
- субъект, предикат, объект или structured payload;
- source refs: `MemorySnapshot`, `MemoryChunk`, `ChatMessage`, email id, external object id, analytics packet;
- evidence snippet hash and position;
- `scope_tokens`;
- `sensitivity`;
- `valid_from`, `valid_to`, `observed_at`;
- `confidence`;
- `status`: `candidate`, `accepted`, `rejected`, `contested`, `superseded`, `expired`;
- `reviewer`, `reviewed_at`, `decision_note`.

### Что такое belief

`Belief` - будущая управляемая позиция системы, собранная из одного или нескольких claims.

Важно: belief не означает "абсолютная истина". Это operational view:

- какой claim сейчас принят;
- какие evidence его поддерживают;
- какие claims ему противоречат;
- кто и когда это утвердил;
- насколько свежая и надежная эта позиция;
- можно ли ее отдавать агенту.

Пример:

```text
Belief:
  "Регуляторные запросы по отделению X должны обрабатываться в течение 3 рабочих дней."

Supports:
  claim from approved policy document
  claim from reviewed email thread

Contradicts:
  older claim from obsolete procedure

State:
  accepted, trusted_context_eligible=true, valid_from=2026-05-01
```

### Почему claim/belief важен

Без этого слоя память работает как "нашли похожий chunk - дали агенту". Это плохо для корпоративной памяти:

- источники могут противоречить друг другу;
- документы устаревают;
- письма могут быть неполными или спорными;
- аналитика может показывать наблюдение, но не причину;
- пользовательская память не должна автоматически становиться организационной правдой.

Claim/belief слой дает:

- проверяемые утверждения вместо неструктурированного текста;
- доказательность через evidence refs;
- явный contested state;
- lifecycle: candidate -> accepted -> superseded/expired;
- компактные digests для дешевого runtime context.

## Lightweight Retrieval Orchestration

### Ограничение

Локальная LLM на потребительском железе не должна выполнять:

- полный reranking десятков chunks;
- source trust decisions;
- NLI/contradiction для каждого запроса;
- глубокую суммаризацию retrieval results в hot path;
- извлечение claims из больших документов по запросу пользователя.

Эти операции либо детерминированные, либо фоновые.

### Runtime budget

Рекомендуемые MVP-лимиты:

| Операция | Бюджет |
| --- | --- |
| Retrieval hot path | без LLM по умолчанию |
| Candidate count до context packing | 20-40 raw candidates |
| Final context items | 3-8 items |
| Context supplement | 500-1200 tokens |
| Optional local LLM rerank | только top 5-8, route flag, timeout |
| Per-request timeout retrieval orchestration | 300-800 ms без LLM |
| LLM claim extraction | только batch/off-peak |

### Дешевый hot path

```text
Query
  -> normalize query
  -> source trust filter
  -> scope/sensitivity filter
  -> FTS/BM25 and vector and graph candidate retrieval
  -> deterministic rank fusion
  -> freshness/authority boosts
  -> context packing with citations
  -> audit trace
  -> optional tiny LLM post-pass only if enabled
```

Rank fusion MVP:

- BM25/FTS score;
- vector score if backend available;
- graph proximity score;
- authority boost for `system_of_record` / reviewed knowledge;
- freshness boost with bounded decay;
- penalty for `candidate`, `contested`, `expired`, `low_confidence`;
- exact scope match boost;
- diversity penalty to avoid returning 5 chunks from same object.

### Фоновые операции

Фоновый контур:

- future claim extraction from trusted/review_required safe corpus;
- contradiction clustering;
- digest compilation;
- future reflection scoring;
- candidate promotion;
- low-quality/stale memory cleanup;
- eval/security scans.

Управление нагрузкой:

- off-peak scheduling;
- batch size limits;
- per-source watermarks;
- cache extraction result by content hash and extractor version;
- incremental recomputation only on changed sources;
- dry-run and budget report mode;
- ability to run with deterministic-only extractor if local LLM unavailable.

## Contract Changes

### `memory_sources.json`

Добавить поля:

```json
{
  "trust_status": "review_required",
  "authority_class": "candidate_input",
  "trusted_for_context": false,
  "requires_source_review": true,
  "review_owner": "knowledge_owner",
  "trusted_context_kinds": ["citation"],
  "untrusted_handling": "review_required"
}
```

### Новый `memory_trust_policy.json`

Рекомендуется отдельный contract:

- allowed `trust_status`;
- allowed `authority_class`;
- defaults by `source_kind`;
- rules for direct context eligibility;
- candidate review roles;
- LLM budget profile for source class.

### Новый `memory_claims_policy.json`

Рекомендуется отдельный contract:

- future claim types;
- future belief states;
- required evidence counts;
- review rules by scope/sensitivity/type;
- freshness windows;
- contradiction handling.

### Новый `memory_retrieval_budget.json`

Рекомендуется отдельный contract:

- hot path limits;
- optional LLM rerank flags;
- top-k limits;
- timeout budgets;
- context token budgets;
- background batch budgets.

## Data Model Proposal

Предварительные модели:

- `MemorySourceTrustReview`
  - source, proposed status, decision, reviewer, evidence, reviewed_at.
- `MemoryClaim`
  - claim id, type, text/structured payload, evidence refs, status, confidence, validity, scope, sensitivity.
- `MemoryBelief` (future runtime layer)
  - belief id, canonical text/payload, status, support claims, contradicting claims, trusted context flag.
- `MemoryBeliefEvent`
  - append-only lifecycle event.
- `MemoryRetrievalTrace`
  - optional detailed trace for rank fusion and context packing if `MemoryAccessAudit` becomes too narrow.

Для текущего MVP `MemoryKnowledgeItem` является главным объектом сохраненного знания. Позже accepted beliefs can also project into graph facts.

## Retrieval Semantics

`memory.search` должен получить параметр или внутренний default:

```text
trusted_context_only=true
```

Поведение:

- direct agent context returns trusted chunks and graph facts only; `MemoryBelief` is not returned by ordinary MVP search;
- candidate/untrusted content can be returned only to review/admin tools;
- citations must include trust status and authority class;
- context text must never include instructions from retrieved data as instructions to the agent;
- future rejected/contested claims are not direct answer context unless user asks for audit/disagreement report and has permission.

## Security Rules

- Trust is enforced by code and contracts, not by prompt text.
- Untrusted content is data, never instruction.
- Source trust does not override scope/sensitivity.
- Trusted source does not override secret/PII routes.
- External authenticated source is not automatically trusted.
- User-owned personal memory is not organization knowledge.
- Future claim extraction from untrusted content must produce candidates, not accepted beliefs.
- Prompt-injection strings in documents/emails/API payloads become security signals and review issues.

## Implementation Tracks

### Track 1. Contracts and validators

- Add trust, claim and budget contracts.
- Extend source contract schema.
- Add validation command coverage.

### Track 2. Source trust gate

- Add source trust decision service.
- Enforce trusted-context-only in retrieval.
- Add tests that untrusted chunks/facts are filtered before context assembly.

### Track 3. Future claim/belief layer

- Add Django models and admin visibility.
- Add deterministic claim writer for reviewed candidates. Explicit memory MVP currently writes `MemoryKnowledgeItem` only.
- Add support/contradiction fields without requiring LLM NLI in MVP.

### Track 4. Lightweight retrieval orchestrator

- Add deterministic rank fusion.
- Add context packing budgets.
- Add trace fields for authority/freshness.
- Keep optional local LLM rerank disabled by default.

### Track 5. Queue processor and future reflection

- Compile small personal/org digests from active `MemoryKnowledgeItem`.
- Current `memory_reflect_chats` is a compatibility queue processor, not full nightly reflection.
- Add stale/expired claim scan.

### Track 6. Security and eval

- Add prompt-injection and memory-poisoning eval cases.
- Add trusted/untrusted source regression tests.
- Add latency/token budget checks for retrieval.

## Acceptance Criteria

- Untrusted source content never appears in normal agent `memory.search` context.
- Review-required sources can still create review candidates.
- Accepted organization knowledge requires review unless source and write path are explicitly trusted.
- Retrieval works without local LLM reranking.
- Runtime context contains citations and trust status.
- Security tests include poisoned documents, emails and API envelopes.
- Documentation explains claim/belief semantics for operators and developers.

## Related Sources

- OpenClaw memory overview: https://docs.openclaw.ai/concepts/memory
- OpenClaw memory-wiki: https://docs.openclaw.ai/plugins/memory-wiki
- Hermes persistent memory docs: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/memory.md
- LangGraph memory concepts: https://langchain-ai.github.io/langgraph/concepts/memory/
- OWASP LLM prompt injection: https://genai.owasp.org/llmrisk/llm01-prompt-injection/
