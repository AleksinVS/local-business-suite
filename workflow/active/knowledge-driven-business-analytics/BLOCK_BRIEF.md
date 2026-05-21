# Workflow brief: knowledge-driven business analytics

## Goal

Create the implementation path for continuous business analytics driven by memory knowledge, email contents, documents and optional DMS/API enrichment.

## Business Value

The system can detect operational risks, repeated issues, regulator requests, missing reports and business deviations from real knowledge streams instead of waiting for users to ask for a report.

## Read Scope

- `apps/analytics/`;
- `apps/memory/`;
- `apps/ai/`;
- `apps/core/`;
- `contracts/analytics/`;
- `contracts/ai/`;
- `contracts/schemas/`;
- `docs/adr/`;
- `docs/architecture/`;
- `docs/guides/`;
- `docs/planning/active/knowledge-driven-business-analytics.md`;
- `workflow/active/knowledge-driven-business-analytics/`.

## Write Scope For Future Implementation

Future implementation packets may write:

- analytics models, services, commands, tests under `apps/analytics/`;
- shared parsing/dedup helpers under `apps/core/` only if used by more than one domain;
- memory handoff integration under `apps/memory/`;
- AI tool definitions and service adapters under `apps/ai/`;
- analytics contracts under `contracts/analytics/` and schemas under `contracts/schemas/`;
- docs, deployment guides and generated structure files.

Runtime data belongs under `data/analytics/` and `data/memory/`. Temporary experiments must stay under `.local/`.

## Non-goals

- No production email credentials in repository files.
- No raw email archive by default.
- No deployment-specific Mango/Bitrix/Renovatio implementation in the universal core.
- No direct AI access to source mailboxes or DMS content without scope rules and audit.
- No organization-wide knowledge publication without review.

## Acceptance

- IMAP is supported as the baseline email source.
- Email body content can be analyzed under explicit source policy.
- One extraction packet can feed memory and analytics.
- Cross-source dedup links email body, attachment, file and DMS evidence to canonical content/facts.
- Analytics store is separate from OLTP and memory.
- Metrics can be recalculated from knowledge/analytics deltas.
- Reflection can propose new metrics and memory candidates.
- AI diagnostics use audited evidence packets and workflow routes.
