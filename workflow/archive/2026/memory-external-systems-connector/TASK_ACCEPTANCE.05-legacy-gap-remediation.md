# Task acceptance: 05-legacy-gap-remediation

Date: 2026-05-20.

## Acceptance Mapping

- Unsafe raw responses are not written to quarantine: implemented and covered by test.
- Unsafe raw responses create landing-zone issue/report: implemented and covered by test.
- Retention cleanup supports dry-run and real delete mode: implemented and covered by test.
- Manifest includes audit/replay fields: implemented and covered by test.
- Delete envelopes append durable tombstones: implemented and covered by test.
- Stale upserts older than tombstone are rejected: implemented and covered by test.
- `content_hash` is recalculated and verified: implemented and covered by test.
- Queue status details show failed/dead-letter errors: implemented and covered by test.

## Verification Commands

```bash
./.venv/bin/python manage.py test apps.memory.tests.MemoryExternalConnectorTests
```

Status: passed.

Final verification:

```bash
./.venv/bin/python manage.py check
./.venv/bin/python manage.py validate_architecture_contracts
./.venv/bin/python manage.py makemigrations --check --dry-run
./.venv/bin/python manage.py test apps.memory.tests apps.core.tests
```

Status: passed.
