# ADR-0006: External System Knowledge Connectors

## Status

Proposed

## Date

2026-05-20

## Context

The memory service already supports governed document ingestion, safe corpus, graph schema bootstrapping, chat-derived personal/organization memory and secret handles. The next question is how to collect knowledge from other information systems: ticket systems, medical systems, inventory systems, CRM/ERP, DMS, analytics systems and other APIs.

The first proposal was to build a connector that fetches data from external APIs, writes files, and lets the existing memory ingestion pipeline extract knowledge from those files. This is directionally correct because it preserves the existing privacy, audit, safe corpus, graph extraction and citation model. It needs a stricter shape: the connector must not dump arbitrary raw API responses into memory. It should write normalized, versioned staging artifacts with manifest, provenance, retention and access metadata.

The system must support:

- initial full sync and later incremental sync;
- API rate limits and backoff;
- durable queueing from the first implementation stage;
- idempotent processing and replay safety;
- deletion/tombstone handling;
- explicit source owner, data owner and schedule decisions;
- privacy and secret gates before memory indexing;
- retention rules for raw responses, normalized staging artifacts, safe corpus and audit metadata.

## Decision

Implement external information system ingestion as a first-class memory connector pattern named **External API Landing Zone**.

Three implementation decisions are accepted for the MVP:

- short-lived raw API response quarantine is allowed when explicitly enabled for a source;
- source-system permissions are mapped to portal `scope_tokens` manually during each source implementation;
- the connector queue must use a separate queue backend from the first implementation stage, not the primary Django database as the authoritative queue store.

The connector architecture is:

```text
External system
  -> source-specific adapter
  -> durable connector queue
  -> normalized staging envelopes and run manifest
  -> existing memory ingestion pipeline
  -> safe corpus, chunks, graph extraction, indexes, citations and audit
```

### Landing Zone

Connectors write normalized envelopes under `data/memory/external_api/` or another runtime data location, never under `contracts/` or the repository root.

The default artifact is not a raw dump. It is a normalized envelope:

```json
{
  "source_code": "external_system_code",
  "object_type": "ticket",
  "external_id": "12345",
  "operation": "upsert",
  "source_updated_at": "2026-05-20T10:00:00Z",
  "content_hash": "sha256...",
  "scope_tokens": ["org:default"],
  "sensitivity": "internal",
  "payload": {},
  "provenance": {
    "connector_version": "external-api-v1",
    "sync_run_id": "..."
  }
}
```

Each run also writes a manifest with counts, cursor state, started/finished timestamps, connector version, schema version, errors and retention class.

### Queue From The First Stage

External connector ingestion must include a durable queue immediately. It must not rely on one long synchronous management command that calls an external API and writes memory in a single transaction.

The first implementation uses a standalone local SQLite queue backend under runtime `data/` as the MVP queue backend. It is intentionally separate from the primary Django database while avoiding a new service dependency before the first pilot. Later stages may replace or complement it with Celery/RQ/RabbitMQ/Redis/PostgreSQL-backed workers or another production queue backend. The contract must remain backend-neutral.

Minimum queue job kinds:

- `discover_external_source`;
- `sync_external_collection`;
- `fetch_external_page`;
- `fetch_external_object`;
- `normalize_external_object`;
- `handoff_external_object_to_memory`;
- `reconcile_external_deletes`;
- `retry_external_failure`;
- `external_dead_letter`.

Each job must have source code, job kind, status, priority, attempt count, `next_attempt_at`, `locked_until`, idempotency key, request/correlation id, payload, result and error message.

### Sync Model

Use this preference order:

1. Native delta/change API if available.
2. Updated-at cursor plus stable object ids.
3. Webhooks plus periodic reconciliation.
4. Full sync on schedule when no reliable delta exists.
5. Manual export into a staging folder as fallback.

CDC tools such as Debezium are suitable for later stages when the organization controls the source database and accepts the operational complexity. CDC is not the default MVP path for third-party or vendor-owned systems.

### Retention

Retention is split by layer:

- raw API response: disabled by default, or short-lived quarantine for debugging when explicitly enabled for a source;
- normalized envelope: retained for a bounded reprocessing window;
- safe corpus and chunks: retained while the memory knowledge is active and citations are needed;
- manifest, hashes, cursors, tombstones and audit: retained longer for deduplication, deletion propagation and investigation;
- secrets: never stored as ordinary payload; only secret handles and metadata may pass through.

### Review and Governance

Every new connector starts with two questionnaires:

- business/source questionnaire for what to collect and how often;
- graph entity/type questionnaire for initial schema understanding.

The questionnaires live in `docs/guides/MEMORY_EXTERNAL_SYSTEMS_QUESTIONNAIRES.md`.

Connector activation requires:

- business owner approval;
- data owner approval;
- technical owner confirmation of API/rate limits;
- security/privacy review for sensitive fields;
- memory owner approval of retention and manually mapped access scope;
- graph owner involvement if the connector introduces new entity/relation types.

## Alternatives Considered

### Direct API adapter to MemorySnapshot

Rejected for MVP. It has lower latency but weaker replay, debugging and audit characteristics. It also couples external API failure modes directly to memory indexing.

### Raw API dumps as files

Rejected as the default. Raw dumps are simple but increase retention and leakage risk. They can be allowed only as short-lived quarantine/debug artifacts with explicit retention and access controls.

### Webhook-only ingestion

Rejected as the only mechanism. Webhooks are useful for freshness but can be duplicated, delayed or missed. They must be paired with periodic reconciliation.

### CDC as the default

Deferred. CDC is strong for owned databases and high-volume near-real-time needs, but it introduces additional infrastructure, source database privileges and operational risk.

### External ETL/iPaaS as memory owner

Rejected as the authoritative path. External ETL tools can fetch or transform data, but they must not bypass Django memory policy, safe corpus, audit and graph governance.

## Consequences

### Positive

- Reuses the existing memory ingestion pipeline and safe corpus.
- Keeps source-specific API code isolated from graph/memory extraction.
- Supports replay, audit, troubleshooting and controlled retention.
- Handles rate limits and retries through durable queues.
- Gives business stakeholders a simple intake process before technical design.

### Negative

- Adds staging storage and standalone queue state.
- Adds latency compared with direct API-to-memory writes.
- Requires retention policy decisions per source.
- Requires connector-specific normalization and mapping work.
- Requires operational monitoring for queue backlog, dead letters and stale cursors.

## Required Follow-up

- Create the architecture plan for external system connectors.
- Add a business questionnaire and graph entity/type questionnaire.
- Add implementation workflow packets.
- Later implementation should add source-specific adapters, cleanup/retention jobs, monitoring UI and production queue backend if pilot load requires it.

## Reference Practices

- Microsoft Graph delta query documents the full-sync then incremental-sync model for API synchronization.
- Microsoft Graph throttling guidance recommends honoring `Retry-After` and backing off requests.
- Azure Queue-Based Load Leveling and Scheduler-Agent-Supervisor patterns motivate durable queues and persistent state for multi-step remote operations.
- Debezium documents CDC as ordered row-level change streams for source databases.
- OWASP guidance warns against secrets in logs and ordinary persisted artifacts.
- AWS Well-Architected guidance recommends data lifecycle rules based on usefulness and required retention.
