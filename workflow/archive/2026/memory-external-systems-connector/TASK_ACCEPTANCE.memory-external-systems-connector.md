# Task acceptance: memory external systems connector MVP

## Acceptance Result

Accepted for MVP documentation and implementation slice.

## Checks

- Business answers are recorded in ADR and architecture docs.
- Queue backend is standalone SQLite under runtime `data/`, not a primary Django DB table.
- Normalized envelopes and manifests are written under runtime `data/memory/external_api/`.
- Raw API responses are stored only when source config enables `short_lived_raw_quarantine`.
- Handoff reuses existing memory snapshot, safe corpus and chunk indexing.
- Secret-like normalized envelope content is blocked before queueing.
- Delete envelopes deactivate active snapshots.

## Verification

Commands run during implementation:

```bash
python manage.py test apps.memory.tests.MemoryExternalConnectorTests
python manage.py check
python manage.py validate_architecture_contracts
python manage.py makemigrations --check --dry-run
```

Default memory contract validation was also run directly against `contracts/ai/`.
