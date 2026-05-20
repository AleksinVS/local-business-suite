# Gap review: external information system connector MVP

Дата: 2026-05-20.

Статус: legacy gap review, remediation slice implemented for pre-pilot gaps.

Связанные документы:

- `docs/adr/ADR-0006-external-system-knowledge-connectors.md`;
- `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_PLAN.md`;
- `docs/guides/MEMORY_EXTERNAL_SYSTEMS_QUESTIONNAIRES.md`;
- `workflow/active/memory-external-systems-connector/`.

## Назначение

Документ фиксирует разрывы между текущим vertical slice реализации external connector MVP и целевой MVP-архитектурой. Эти разрывы считаются **legacy gaps**: текущий код можно использовать как ограниченный MVP-контур, но перед подключением реального чувствительного источника их нужно закрыть или явно принять как риск.

## Текущий статус

Реализовано:

- standalone SQLite queue backend, отдельный от primary Django DB;
- normalized landing zone under `data/memory/external_api/`;
- generic enqueue/worker/status/cleanup commands;
- handoff normalized envelope -> `MemorySnapshot` -> safe corpus/chunks;
- secret scan normalized envelope before queueing;
- DLP/secret gate for raw quarantine with landing-zone issue when raw is skipped;
- idempotency by `source/collection/external_id/content_hash`;
- canonical `content_hash` verification;
- delete envelope deactivates active snapshot and appends durable tombstone;
- stale upsert protection after tombstone;
- retention cleanup command with dry-run/default safe mode;
- queue status details for failed/retry/dead-letter jobs;
- contract extensions for `external_api_snapshot`.

Проверки на момент ревью:

```bash
python manage.py test apps.memory.tests.MemoryExternalConnectorTests
python manage.py check
python manage.py validate_architecture_contracts
python manage.py makemigrations --check --dry-run
```

Все проверки прошли.

## Legacy Gaps

### 1. Raw quarantine is plaintext and not encrypted

Severity: High.

Target architecture:

- `short_lived_raw_quarantine` is allowed only as a bounded protected debug contour;
- architecture plan describes it as encrypted raw response storage;
- raw responses may contain PII, secrets or source-system sensitive fields.

Current implementation:

- raw API response is written as ordinary JSON under `raw_quarantine/` only after DLP/secret gate;
- if credential material is detected, raw payload is not written and an issue is recorded;
- no encryption.

Risk:

- enabling raw quarantine for a real source may create a plaintext sensitive-data dump under runtime storage.

Remediation:

- encryption at rest is deferred to a later hardening stage;
- add access/permissions guidance for runtime directory;
- DLP/secret gate and tests are implemented in the remediation slice.

### 2. Retention policy is declared but not enforced

Severity: High.

Target architecture:

- `raw_quarantine_days`, `normalized_envelope_days`, `manifest_days` and `tombstone_days` define actual lifecycle behavior.

Current implementation:

- retention values exist in source config;
- `memory_external_cleanup` enforces expiry by command with dry-run/default safe mode;
- scheduling of the cleanup command is deployment-specific.

Risk:

- short-lived quarantine and normalized landing zone can become indefinite storage.

Remediation:

- implemented `memory_external_cleanup`;
- deploy scheduled execution per environment.

### 3. Manifest is incomplete for audit/replay

Severity: Medium.

Target architecture:

- manifest should include counts, cursor state, started/finished timestamps, connector version, schema version, errors and retention class.

Current implementation:

- manifest includes schema version, connector version, source, run id, started/finished timestamps, queue backend, retention, retention class, cursor state, object count, error count, issues path and objects list.

Risk:

- replay, audit and troubleshooting are weak for real sync runs.

Remediation:

- implemented and covered by tests.

### 4. Queue declares full job taxonomy but worker supports only handoff

Severity: Medium.

Target architecture:

- queue supports discover/sync/fetch/normalize/handoff/reconcile/retry/dead-letter stages.

Current implementation:

- job kind constants exist for the full taxonomy;
- worker processes only `handoff_external_object_to_memory`;
- other job kinds fail as unsupported.

Risk:

- a real source-specific adapter still needs the sync/fetch/normalize parts; current MVP is a handoff queue, not a complete connector pipeline.

Remediation:

- implement source-specific adapter runner after pilot source selection;
- add worker dispatch registry for job kinds;
- add retry/backoff semantics per source API;
- add tests for fetch/normalize/reconcile stages.

### 5. Tombstone/deletion state is not durable enough

Severity: Medium.

Target architecture:

- tombstones are long-lived to prevent deleted records from reappearing during replay or faulty sync.

Current implementation:

- delete envelope deactivates active snapshots;
- delete envelope appends durable tombstone under `data/memory/external_api/<source>/tombstones/`;
- stale upserts older than tombstone are rejected.

Risk:

- deleted objects may reappear if source sync replays old upserts or adapter misses deletion state.

Remediation:

- implemented tombstone artifact with source/version/deleted_at metadata and stale upsert protection.

### 6. Envelope content hash is trusted, not verified

Severity: Medium.

Target architecture:

- content hash should be a reliable version/deduplication boundary.

Current implementation:

- `validate_external_envelope` recalculates canonical hash input and rejects mismatches before queueing/handoff.

Risk:

- buggy or manual adapters can break idempotency and snapshot versioning.

Remediation:

- implemented canonical hash verification; no unaudited override is exposed in MVP.

### 7. Documentation status is slightly optimistic

Severity: Low/Medium.

Target architecture:

- MVP wording should distinguish between a complete connector MVP and a vertical slice.

Current implementation:

- plan states "MVP standalone queue, landing zone, enqueue/worker/status commands and handoff implemented";
- this is accurate for vertical slice but can be misread as full source connector readiness.

Risk:

- operators may assume real external systems can be connected without source-specific adapter, retention cleanup and hardened quarantine.

Remediation:

- consistently label current state as "MVP vertical slice";
- keep the legacy gaps linked from the main plan and backlog.

## Acceptance Boundary

Current implementation is acceptable for:

- validating normalized envelope shape;
- local tests with synthetic/non-sensitive payloads;
- testing queue handoff to memory snapshots/chunks;
- preparing pilot source implementation.

Current implementation is not sufficient for:

- enabling raw quarantine on sensitive production systems without additional hardening;
- relying on retention lifecycle;
- full API sync with cursor/delta/retry/fetch/normalize stages;
- deletion protection across replay without tombstones.

## Recommended Next Legacy Remediation Order

1. Schedule `memory_external_cleanup` in deployment once the first pilot source is enabled.
2. Add runtime directory permission hardening notes per host.
3. Add source-specific pilot adapter after source selection.

Deferred until pilot/source-specific stage:

- raw quarantine encryption at rest;
- worker dispatch handlers for real discover/sync/fetch/normalize stages;
- source-specific adapter;
- webhooks/reconciliation.
