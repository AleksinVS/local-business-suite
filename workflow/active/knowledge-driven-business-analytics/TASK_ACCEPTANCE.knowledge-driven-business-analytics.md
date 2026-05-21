# Task acceptance: knowledge-driven business analytics MVP

Дата: 2026-05-21.

## Accepted MVP behavior

- Contracts validate through the architecture contract validator.
- IMAP-style fixture sources can be synced into analytics content objects.
- Email body content is analyzed and converted into extraction packets and analytics facts.
- Duplicate report-like messages create duplicate candidates.
- Metrics are recalculated from analytics facts.
- Monitors create analytics signals.
- Reflection proposes metric candidates from observed fact types.
- Diagnostic runs build scoped evidence packets and can create draft analytics cases.

## Acceptance notes

- Raw email archive is not enabled by default.
- Source credentials are not represented in repository contracts.
- DMS is represented as an interface/contract concern and not bound to a concrete product.
- JSONL is accepted as the dependency-free runtime dataset format for this MVP slice; Parquet/DuckDB remains the target store from the architecture plan.
