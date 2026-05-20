# Active plan: устранение legacy gaps external connector MVP

Статус: implemented, pending final verification/acceptance.

Дата: 2026-05-20.

## Цель

Устранить разрывы текущего external connector MVP vertical slice, которые можно закрыть до выбора pilot source:

- DLP/secret gate для raw quarantine;
- retention cleanup для landing zone и raw quarantine;
- расширенный manifest для audit/replay;
- durable tombstone registry;
- verification `content_hash`;
- уточнение документации и workflow acceptance;
- CLI visibility для queue/dead-letter details.

Шифрование raw quarantine сознательно переносится на последующие этапы.

## Контекст

- Архитектурное решение: `docs/adr/ADR-0006-external-system-knowledge-connectors.md`.
- Основной план: `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_PLAN.md`.
- Gap review: `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_GAP_REVIEW.md`.
- Workflow package: `workflow/active/memory-external-systems-connector/`.

## Scope

### In Scope

- Проверять raw response на secrets/credential material перед записью в quarantine.
- Если raw response небезопасен, не писать raw и фиксировать issue/report в landing zone.
- Добавить cleanup command with `--dry-run` для expired raw quarantine, normalized envelopes и manifests.
- Расширить manifest до минимального audit/replay формата.
- Добавить tombstone registry under `data/memory/external_api/<source>/tombstones/`.
- Проверять `content_hash` normalized envelope against canonical hash.
- Добавить `memory_external_queue_status --details --limit N`.
- Обновить tests, deployment docs и workflow acceptance.

### Out Of Scope

- Encryption at rest для raw quarantine.
- Source-specific API adapter.
- Full discover/sync/fetch/normalize worker stages.
- Webhooks/reconciliation.
- Production queue backend beyond standalone SQLite.
- UI/admin monitoring.

## Acceptance Criteria

- Raw quarantine never writes payloads with detected credential material.
- Retention cleanup supports dry-run and real mode.
- Manifest includes schema version, connector version, started/finished timestamps, object count, error count, cursor state, retention class and issues path.
- Delete envelopes append durable tombstones.
- Stale upsert older than tombstone is rejected or skipped according to policy.
- Envelope `content_hash` is recalculated and verified before queueing/handoff.
- Queue status can show recent failed/dead-letter jobs with error messages.
- Tests cover all new behavior.

## Verification Commands

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py makemigrations --check --dry-run
python manage.py test apps.memory.tests.MemoryExternalConnectorTests
python manage.py test apps.memory.tests apps.core.tests
```

## Execution Notes

- Do not write runtime data in repo root.
- Temporary test artifacts must stay in `.local/` or test temp directories.
- Runtime cleanup command must be safe by default and use `--dry-run`.
- Do not introduce a new service dependency for this remediation slice.

## Implementation Result

Implemented in task packet `05-legacy-gap-remediation`:

- raw quarantine DLP/secret gate with `issues.jsonl` when unsafe raw payload is skipped;
- manifest audit/replay fields;
- durable tombstone registry and stale upsert rejection;
- canonical `content_hash` verification;
- `memory_external_cleanup` command with dry-run/default safe mode and `--yes` real delete mode;
- `memory_external_queue_status --details --limit N`;
- tests in `MemoryExternalConnectorTests`.
