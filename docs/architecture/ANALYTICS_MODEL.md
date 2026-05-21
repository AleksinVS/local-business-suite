# Analytics Model

Extended target architecture:

- `docs/adr/ADR-0008-knowledge-driven-business-analytics.md` defines analytics as a continuous knowledge-driven business control loop.
- `docs/architecture/KNOWLEDGE_DRIVEN_ANALYTICS_PLAN.md` describes email content analysis, memory-driven analytics, DMS integration, scope rules, dedup/provenance and AI diagnostic workflows.

Current implementation:

- `apps.analytics` is an operational dashboard over the Django OLTP database.
- Dataset defaults are declared in `contracts/analytics/datasets.json`; runtime copies live in `data/contracts/analytics/`.
- This layer is intended for lightweight operational summaries, not heavy BI/reporting workloads.

Future target stack:

- `Parquet` as exported analytical storage;
- `DuckDB` as analytical query engine;
- `Evidence` as analytics-as-code presentation layer.

Flow:

1. Django writes OLTP data to SQLite.
2. Export jobs create `raw` Parquet datasets in `data/analytics/raw/`.
3. Curated transformations build marts in `data/analytics/marts/`.
4. DuckDB reads Parquet datasets and serves analytical queries.
5. Evidence renders analytical pages from curated SQL sources.

Rules:

- heavy reporting must not read live OLTP tables;
- datasets are versioned in `contracts/analytics/datasets.json` and copied to `data/contracts/analytics/`;
- analytical changes should be reviewed like code changes.
