# Executor report: memory external systems connector

## Status

Implemented MVP slice on 2026-05-20.

## Completed

- Fixed the three accepted decisions in ADR, architecture plan and questionnaire guide:
  - short-lived raw API response quarantine is allowed per source;
  - external permissions use manual `scope_tokens` mapping during source implementation;
  - queue backend is required from the first implementation and is separate from the primary Django database.
- Added standalone SQLite external connector queue backend under `data/memory/queues/`.
- Added normalized external envelope builder, landing zone writer and manifest output under `data/memory/external_api/`.
- Added optional raw response quarantine when source config enables `short_lived_raw_quarantine`.
- Added handoff from normalized envelopes to `MemorySnapshot`, safe corpus and chunks.
- Added generic management commands:
  - `memory_external_enqueue`;
  - `memory_external_worker`;
  - `memory_external_queue_status`.
- Extended memory source contracts and validators for `external_api_snapshot`, manual scope mapping and external retention.
- Added tests for queue idempotency, handoff, secret blocking, delete/tombstone behavior and command smoke.

## Files Changed

- `apps/memory/external_connectors.py`
- `apps/memory/management/commands/memory_external_enqueue.py`
- `apps/memory/management/commands/memory_external_worker.py`
- `apps/memory/management/commands/memory_external_queue_status.py`
- `apps/memory/tests.py`
- `apps/core/json_utils.py`
- `config/settings.py`
- `contracts/ai/memory_sources.json`
- `contracts/ai/memory_profiles.json`
- `contracts/ai/memory_ingestion_profiles.json`
- `contracts/schemas/memory_sources.schema.json`
- memory architecture, deployment, planning and workflow docs

## Remaining Work

- Select the first pilot external system.
- Implement a source-specific adapter for that pilot.
- Add retention cleanup command for expired raw quarantine/envelopes.
- Add monitoring UI/admin if queue operations need non-CLI visibility.
- Decide after pilot whether standalone SQLite queue is enough or a service queue is required.
