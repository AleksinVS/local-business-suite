# Executor report: 05-legacy-gap-remediation

Date: 2026-05-20.

## Scope

Implemented the pre-pilot remediation package for the external connector MVP vertical slice without adding a source-specific adapter.

## Changes

- Added DLP/secret gate before writing `short_lived_raw_quarantine` raw API responses.
- Added landing-zone `issues.jsonl` output when unsafe raw payload is skipped.
- Extended run manifest with schema version, connector version, timestamps, object/error counts, cursor state, retention class and issues path.
- Added canonical external envelope `content_hash` verification.
- Added durable tombstone registry under `data/memory/external_api/<source>/tombstones/`.
- Added stale upsert rejection after tombstone.
- Added `memory_external_cleanup` command with dry-run/default safe mode and `--yes` delete mode.
- Added `memory_external_queue_status --details --limit` for retry/dead-letter visibility.
- Added tests for the remediation behavior.

## Non-goals Preserved

- Raw quarantine encryption remains deferred.
- No source-specific adapter was added.
- No webhook/reconciliation or production queue backend was added.
- No UI/admin monitoring was added.

## Verification

Initial focused check:

```bash
./.venv/bin/python manage.py test apps.memory.tests.MemoryExternalConnectorTests
```

Status: passed.

Full verification is tracked in `TASK_ACCEPTANCE.05-legacy-gap-remediation.md`.

Final status: full verification passed.
