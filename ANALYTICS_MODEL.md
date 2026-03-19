# Analytics Model

Target stack:

- `Parquet` as exported analytical storage;
- `DuckDB` as analytical query engine;
- `Evidence` as analytics-as-code presentation layer.

Flow:

1. Django writes OLTP data to SQLite.
2. Export jobs create `raw` Parquet datasets in `analytics_store/raw/`.
3. Curated transformations build marts in `analytics_store/marts/`.
4. DuckDB reads Parquet datasets and serves analytical queries.
5. Evidence renders analytical pages from curated SQL sources.

Rules:

- analytics do not read live OLTP tables for heavy reporting;
- datasets are versioned in `analytics_store/datasets.json`;
- analytical changes should be reviewed like code changes.
