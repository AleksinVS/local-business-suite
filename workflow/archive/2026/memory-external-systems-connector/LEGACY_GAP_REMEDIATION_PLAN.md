# Legacy gap remediation plan: external connector MVP

## Goal

Close the legacy gaps that can be fixed before choosing the first real external information system.

Encryption for raw quarantine is explicitly deferred to a later security-hardening stage. This remediation focuses on preventing unsafe raw writes, enforcing retention, improving replay/audit metadata and making queue failures visible.

## Read Scope

- `apps/memory/external_connectors.py`;
- `apps/memory/management/commands/memory_external_*.py`;
- `apps/memory/tests.py`;
- `contracts/ai/memory_sources.json`;
- `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_GAP_REVIEW.md`;
- `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_PLAN.md`;
- `docs/deployment/MEMORY_DEPLOYMENT.md`;
- `workflow/active/memory-external-systems-connector/`.

## Write Scope

- `apps/memory/external_connectors.py`;
- `apps/memory/management/commands/`;
- `apps/memory/tests.py`;
- docs and workflow files related to external connector gap remediation;
- `PROJECT_STRUCTURE.yaml` if new files are added.

Do not write source-specific adapters in this remediation slice.

## Non-goals

- No raw quarantine encryption.
- No real API adapter.
- No webhook/reconciliation.
- No production queue backend.
- No UI/admin monitoring.

## Execution Order

1. Raw quarantine DLP gate and issue/report output.
2. Manifest completeness.
3. Tombstone registry and stale upsert protection.
4. Envelope content hash verification.
5. Retention cleanup command.
6. Queue status details.
7. Tests and docs refresh.

## Acceptance

- Unsafe raw API responses are not written to quarantine.
- Cleanup can remove expired runtime artifacts with `--dry-run` support.
- Manifest is sufficient for audit/replay of a run.
- Tombstones survive snapshot deactivation and block stale replays.
- Invalid `content_hash` is rejected before queue/handoff.
- Queue status can inspect failed/dead-letter jobs.
- Verification commands listed in the active plan pass.

## Execution Status

Implemented on 2026-05-20 in task packet `05-legacy-gap-remediation`.

Implemented items:

- raw quarantine DLP/secret gate and landing-zone issue output;
- extended manifest;
- durable tombstones and stale upsert protection;
- canonical `content_hash` verification;
- `memory_external_cleanup`;
- `memory_external_queue_status --details --limit`;
- focused tests in `MemoryExternalConnectorTests`.
