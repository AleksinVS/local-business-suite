# Executor report: knowledge-driven business analytics MVP

Дата: 2026-05-21.

## Scope implemented

- Added analytics contracts for sources, scope rules, business facts, metrics, monitors, diagnostic playbooks, workflow routes, dedup rules and retention profiles.
- Added JSON schemas and contract validators.
- Added analytics control-plane models for sources, extraction runs, content objects, extraction packets, evidence refs, duplicate candidates, facts, metric snapshots, signals, diagnostics, cases, metric candidates, sample manifests and access audit.
- Added fixture-first IMAP baseline sync path for MVP/dry-run usage without storing mailbox credentials in the repository.
- Added shared extraction packet that materializes business facts from email content and can be used for memory/analytics handoff.
- Added cross-source dedup candidate logic using raw hash, normalized text hash, business key and near-duplicate key.
- Added JSONL runtime dataset writer under `data/analytics/` as dependency-free MVP fallback until Parquet/DuckDB dependencies are introduced.
- Added metric recalculation, monitor evaluation, analytics signal creation, reflection over facts and diagnostic run/case creation.
- Added management commands:
  - `analytics_sync_source`;
  - `analytics_extract_source`;
  - `analytics_dedup_source`;
  - `analytics_recalculate_metrics`;
  - `analytics_reflect_knowledge`;
  - `analytics_run_diagnostic`.
- Fixed `analytics.summary` AI service permission check to use `view_analytics` instead of `manage_inventory`.

## Deferred beyond MVP

- Real IMAP network connection and IMAP IDLE loop.
- Real DMS adapter implementation for a concrete product.
- Production RabbitMQ/Celery worker wiring.
- Native Parquet/DuckDB writer/query adapter; current implementation uses JSONL runtime datasets because the project does not currently depend on `pyarrow`, `pandas` or `duckdb`.
- LLM-backed extraction; current extractor is deterministic pattern-based.

## Verification

Executed during implementation:

```bash
python manage.py validate_architecture_contracts
python manage.py test apps.analytics.tests
```

Full final verification is recorded in the turn summary.
