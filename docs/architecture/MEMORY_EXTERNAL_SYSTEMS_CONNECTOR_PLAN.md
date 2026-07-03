# План: сбор знаний из внешних информационных систем

Статус: архитектурный план; MVP vertical slice implemented 2026-05-20, production queue backend updated to database table by ADR-0029 on 2026-06-15.

Legacy gap review: `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_GAP_REVIEW.md`.

Дополнение 2026-05-22: handoff внешнего коннектора больше не создает постоянные `MemorySnapshot`/`MemoryChunk`. Нормализованный объект внешней системы записывается как `MemorySourceObject`, а для поиска создается `MemorySearchDocument`. Старые упоминания safe corpus/chunks ниже являются историей исходного проектирования и заменяются файловой схемой знаний из ADR-0011.

Дополнение 2026-05-26: generic connector MVP считается reference implementation. Source-specific adapter, production schedule и развитие внешнего коннектора заморожены до выбора pilot source, владельца данных, sensitivity, scope mapping и retention.

Дополнение 2026-06-15: после решения о PostgreSQL как основном хранилище production queue backend для внешних коннекторов - `MemoryExternalConnectorJob` в основной БД. Standalone SQLite queue остается dev/legacy backend для SQLite-fork и локальных тестов.

Дата: 2026-05-20.

Связанные документы:

- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- `docs/adr/ADR-0006-external-system-knowledge-connectors.md`;
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`;
- `docs/guides/MEMORY_EXTERNAL_SYSTEMS_QUESTIONNAIRES.md`.

## Назначение

Документ описывает архитектуру сбора знаний из внешних информационных систем: API, выгрузок, webhook-событий, внутренних БД и будущих ETL/CDC-контуров.

Цель - не просто импортировать данные, а безопасно превратить внешние записи в управляемую память: с provenance, правами доступа, retention, safe corpus, citations и graph extraction.

## Вывод после повторного анализа

Исходное предложение "коннектор подключается к API и загружает данные в файлы, а дальше знания собирает существующий процесс" подходит для MVP, если заменить "файлы" на более строгую конструкцию:

```text
External API Landing Zone = manifest + normalized envelopes + queue + retention rules
```

Коннектор не должен писать произвольный raw JSON прямо в память. Он должен:

- получать данные из внешней системы;
- нормализовать их в стабильный envelope;
- сохранять provenance и source metadata;
- передавать envelope в существующий memory ingestion;
- не обходить privacy gate, secret handling, safe corpus и graph governance.

## Зафиксированные ответы

- Raw API responses можно хранить в `short_lived_raw_quarantine`, если это явно включено для конкретного source и задан срок retention.
- Маппинг прав внешней системы в `scope_tokens` портала на первом этапе ручной и определяется при внедрении конкретного source.
- Очередь нужна сразу как отдельный queue backend. Production backend теперь использует `MemoryExternalConnectorJob` в основной БД; standalone SQLite queue under `data/memory/queues/` остается dev/legacy вариантом.

## Архитектурные варианты

### Вариант A: API -> normalized files -> existing memory ingestion

Рекомендуемый MVP.

Плюсы:

- переиспользует текущий ingestion/safe corpus/graph extraction;
- упрощает replay и отладку;
- хорошо разделяет внешний API и память;
- staging artifacts можно проверять до публикации знаний;
- проще реализовать retention по слоям.

Минусы:

- есть дополнительная задержка;
- нужен контроль staging storage;
- нужны правила удаления и очистки.

### Вариант B: API -> MemorySnapshot напрямую

Подходит для отдельных малых интеграций, но не как общий pattern.

Плюсы:

- меньше промежуточных артефактов;
- меньше задержка.

Минусы:

- сложнее повторить ingestion;
- выше риск смешать API adapter и memory extraction;
- труднее расследовать ошибки и partial ingestion.

### Вариант C: webhook/event inbox + reconciliation

Подходит для данных, где важна свежесть.

Плюсы:

- почти мгновенное обновление;
- меньше polling.

Минусы:

- webhooks могут дублироваться или теряться;
- все равно нужен периодический reconciliation;
- сложнее security exposure входящего endpoint.

### Вариант D: CDC из БД источника

Подходит для больших внутренних систем, если организация контролирует БД.

Плюсы:

- высокая полнота изменений;
- хорошая свежесть;
- не нужно дергать API.

Минусы:

- доступ к БД и журналам изменений часто недоступен;
- сложнее эксплуатация;
- может быть слишком тяжелым для MVP.

### Вариант E: внешний ETL/iPaaS

Подходит как источник staged data, но не как владелец памяти.

Плюсы:

- готовые коннекторы;
- меньше кода для популярных систем.

Минусы:

- риск обойти memory policy;
- отдельная эксплуатация и лицензирование;
- governance должен оставаться в Django memory.

## Целевой MVP pattern

```text
External system
  -> ExternalSource contract
  -> Connector adapter
  -> Durable queue
  -> Sync run manifest
  -> Normalized object envelopes
  -> Memory source object / snapshot handoff
  -> Privacy and secret gates
  -> Safe corpus
  -> Chunks and graph extraction
  -> Search / graph facts / citations / audit
```

## Landing Zone

Runtime data lives under:

```text
data/memory/external_api/<source_code>/<run_id>/
  manifest.json
  objects/
    <object_type>/<external_id>.json
  raw_quarantine/
    <object_type>/<external_id>.json
  issues.jsonl

data/memory/external_api/<source_code>/tombstones/
  <collection>/<object_type>.jsonl
```

This directory is runtime data. It is not committed.

MVP queue runtime data lives under:

```text
data/memory/queues/external_connectors.sqlite3
```

Default raw mode:

```text
normalized_only
```

Allowed modes:

- `metadata_only` - store only cursor/hash/metadata, no object payload;
- `normalized_only` - store normalized safe-intended envelope, default MVP;
- `short_lived_raw_quarantine` - store raw response for bounded debug window after DLP/secret gate; encryption at rest is deferred to a later hardening stage;
- `immutable_raw_vault` - future explicit mode for regulated reproducibility, not MVP default.

## Normalized Envelope

Minimum shape:

```json
{
  "schema_version": "external-memory-envelope-v1",
  "source_code": "external_system_code",
  "collection": "tickets",
  "object_type": "ticket",
  "external_id": "12345",
  "external_url": "https://source.example/tickets/12345",
  "operation": "upsert",
  "source_created_at": "2026-05-01T10:00:00Z",
  "source_updated_at": "2026-05-20T10:00:00Z",
  "etag_or_version": "abc",
  "content_hash": "sha256...",
  "title": "Short human title",
  "payload": {},
  "relations": [],
  "scope_tokens": ["org:default"],
  "sensitivity": "internal",
  "retention_class": "external_default",
  "provenance": {
    "connector_version": "external-api-v1",
    "sync_run_id": "2026-05-20T10-00-00Z",
    "fetched_at": "2026-05-20T10:01:00Z"
  }
}
```

The payload should be normalized before handoff:

- stable field names;
- only fields approved by the intake questionnaire;
- explicit relations;
- explicit sensitivity;
- no secrets as ordinary values;
- enough text for citations and user-facing evidence.

## Queue Requirements

Queue support is required from the first connector implementation.

First-stage queue backend is now selected by deployment profile. Production uses `LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND=database`; dev/legacy can use a standalone SQLite queue file under:

```text
data/memory/queues/external_connectors.sqlite3
```

The model must not lock the architecture into SQLite-only queueing. Later production deployment may move to a service queue such as RabbitMQ/Redis/Celery/RQ when pilot volume or reliability requirements justify it.

### Job fields

- `source`;
- `run`;
- `job_kind`;
- `status`;
- `priority`;
- `payload`;
- `result`;
- `idempotency_key`;
- `attempt_count`;
- `max_attempts`;
- `next_attempt_at`;
- `locked_until`;
- `started_at`;
- `finished_at`;
- `created_by` or service identity;
- `request_id`;
- `error_message`.

### Job statuses

```text
pending
leased
running
succeeded
retry_wait
failed
dead_letter
cancelled
```

### Job kinds

```text
discover_external_source
sync_external_collection
fetch_external_page
fetch_external_object
normalize_external_object
handoff_external_object_to_memory
reconcile_external_deletes
retry_external_failure
external_dead_letter
```

### Queue rules

- Every job must be idempotent.
- Use source/object/version hashes to avoid duplicate memory snapshots.
- Honor source API rate limits and `Retry-After` when available.
- Use exponential backoff for transient failures.
- Move repeated failures to issue/dead-letter queue.
- Keep partial progress in durable state.
- Do not hold long database transactions while calling external APIs.
- Workers must be safe to run concurrently.

## Sync Strategy

Preference order:

1. Native delta API or change token.
2. Updated-at cursor with stable ids and periodic full reconciliation.
3. Webhooks for freshness plus scheduled reconciliation.
4. Full sync if the source is small or has no reliable delta.
5. Manual export into a staging folder as fallback.
6. CDC only for controlled internal databases and later stages.

## Retention Policy

Default recommendation:

| Layer | Default | Rationale |
| --- | --- | --- |
| raw API response | do not store unless source enables quarantine | reduce leakage and retention risk |
| raw quarantine | 7-30 days if explicitly enabled | debugging and incident analysis |
| normalized envelopes | 30-90 days | replay/reprocessing window |
| manifest/cursors/hashes | 1-3 years or policy-defined | audit, dedupe, deletion propagation |
| safe corpus/chunks | while knowledge is active | citations and retrieval |
| tombstones | long-lived | prevent deleted records from reappearing |
| secret values | never | only handles/metadata allowed |

Retention must be answered per source in the business questionnaire and stored in the source contract.

## Access Model

MVP uses manual explicit scope mapping:

- `scope_rule`;
- source-level default scope tokens;
- field/object-level sensitivity metadata when available.

Later stages may map external ACLs or roles to internal scope tokens. This must be designed carefully because source-system permissions often do not map cleanly to portal roles.

## Security and Privacy Gates

Connector boundary checks:

- no connector credentials in contracts or logs;
- no secrets in envelope payloads;
- secret-like values become handles or blocked fields according to policy;
- PII/sensitive fields are either excluded, deidentified or marked with sensitivity;
- raw quarantine requires explicit retention and access control;
- external URLs are citations, not authorization bypasses.

Memory handoff checks:

- existing DLP/secret scan;
- deidentification where policy requires it;
- safe corpus write only after privacy gate;
- issue queue for blocked or partial objects.

## Intake Process

1. Business owner fills `Опросник 1`.
2. Profile expert and graph owner fill or validate `Опросник 2`.
3. Architect prepares source profile and sync strategy.
4. Security/privacy owner approves sensitive fields and retention.
5. Technical owner confirms API access, rate limits and delta capability.
6. Memory owner approves ingestion route and schedule.
7. Implementation starts from a narrow safe pilot.

## Proposed Implementation Tasks

MVP vertical slice implemented:

1. Source contract/schema extensions for `external_api_snapshot`.
2. Database connector queue `MemoryExternalConnectorJob`; standalone SQLite connector queue remains dev/legacy.
3. Filesystem landing zone writer with audit/replay manifest and normalized envelope files.
4. Optional `short_lived_raw_quarantine` raw response storage behind DLP/secret gate.
5. Generic enqueue/worker/status/cleanup management commands.
6. Handoff adapter from normalized envelope to `MemorySourceObject` and `MemorySearchDocument`.
7. Canonical `content_hash` verification before queue/handoff.
8. Durable tombstone registry with stale upsert protection.
9. Tests for idempotency, secret blocking, raw quarantine DLP skip, cleanup, tombstones and commands.

Remaining implementation tasks:

1. Add source-specific pilot adapter after the first external system is selected.
2. Add queue monitoring UI/admin if needed.
3. Add webhook/reconciliation support if pilot freshness requires it.
4. Add production queue backend if SQLite is not sufficient after pilot load tests.
5. Add raw quarantine encryption at rest during the later security-hardening stage.

Legacy gaps are tracked in `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_GAP_REVIEW.md`. The current slice is suitable for synthetic/non-sensitive envelope handoff tests and pilot preparation. Sensitive raw quarantine still requires the deferred encryption hardening and source-specific security review.

## MVP Commands

```bash
python manage.py memory_external_enqueue --source-code <source> --envelope-file <path>
python manage.py memory_external_worker --limit 10
python manage.py memory_external_queue_status
python manage.py memory_external_queue_status --details --limit 20
python manage.py memory_external_cleanup --source-code <source> --dry-run
```

Dry-run examples:

```bash
python manage.py memory_external_enqueue --source-code <source> --envelope-file <path> --dry-run
python manage.py memory_external_worker --dry-run
```

## Questions Still Worth Discussing

No question blocks documentation or MVP planning. Before implementation, these decisions should be made per first real source:

- Which external system is the pilot?
- Is there a reliable delta API, or do we start with scheduled full/incremental sync by `updated_at`?
- What freshness target is acceptable for the pilot?
- What exact retention is allowed for normalized envelopes?
- Which sensitive fields must be excluded before landing zone?
- Who owns connector failures operationally?
- Do we need webhooks in MVP, or polling is enough?
- Is standalone SQLite queue sufficient for the expected first-source volume, or does pilot require RabbitMQ/Redis/Celery/RQ?

## Non-goals for MVP

- No direct writes from external API into graph facts without safe corpus/provenance.
- No unbounded raw API dump retention.
- No CDC infrastructure unless the first source explicitly requires it.
- No universal ACL inheritance from all source systems.
- No generic low-code connector builder in the first implementation.
