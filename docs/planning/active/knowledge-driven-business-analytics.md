# Knowledge-driven business analytics

Статус: active planning; MVP vertical slice implemented 2026-05-21, production connectors and Parquet/DuckDB backend remain follow-up tracks.

Дата создания: 2026-05-21.

Связанные документы:

- `docs/adr/ADR-0008-knowledge-driven-business-analytics.md`;
- `docs/architecture/KNOWLEDGE_DRIVEN_ANALYTICS_PLAN.md`;
- `docs/guides/KNOWLEDGE_ANALYTICS_OPERATIONS.md`;
- `docs/architecture/ANALYTICS_MODEL.md`;
- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0006-external-system-knowledge-connectors.md`;
- `workflow/active/knowledge-driven-business-analytics/`.

## Goal

Сформировать и реализовать универсальный контур непрерывной бизнес-аналитики на базе знаний из памяти, содержимого электронной почты, документов и optional DMS/API-источников.

Контур должен:

- извлекать знания и аналитические факты за один проход;
- анализировать содержимое писем, а не только metadata;
- пересчитывать метрики при появлении новых знаний;
- рефлексивно находить закономерности и предлагать новые метрики;
- защищаться от дублей между email, attachments, file storage и DMS;
- запускать AI diagnostics and workflow routing при отклонениях.

## Scope

### In scope

- architecture contracts for analytics sources, scope rules, facts, metrics, monitors and dedup;
- IMAP baseline email ingestion;
- email body and attachment content analysis;
- memory delta to analytics fact materialization;
- cross-source dedup/provenance registry;
- analytics runtime storage under `data/analytics/`;
- DuckDB/Parquet MVP analytical store;
- DMS optional connector interface;
- AI diagnostic workflow and metric candidate review;
- operations docs and smoke checks.

### Non-goals

- no production mailbox credentials in the main repository;
- no full email archive by default;
- no direct AI access to mailboxes without scope rule and audit;
- no automatic publication of organization-wide knowledge without review;
- no deployment-specific Mango/Bitrix/Renovatio implementation in the universal core;
- no mandatory Microsoft 365 or Google Workspace dependency.

## Architecture Decisions

- IMAP is the baseline email protocol.
- Microsoft Graph and Gmail adapters are optional enhanced adapters.
- Extraction uses the `extract once, derive many` pattern.
- DMS remains source of truth when present.
- Dedup works at source id, exact content, near-duplicate and semantic claim levels.
- Analytics bulk data lives in `data/analytics/` as Parquet; Django DB stores control plane.
- RabbitMQ/Celery is the preferred production MVP direction for continuous analytics jobs.

## Implementation Tracks

### Track 1. Contracts and validation

Add contract files and JSON schemas for:

- analytics sources;
- analysis scope rules;
- business facts;
- metrics;
- monitors;
- diagnostic playbooks;
- workflow routes;
- dedup rules;
- retention profiles.

### Track 2. IMAP email ingestion

Implement:

- mailbox source config;
- folder allowlist/denylist;
- UIDVALIDITY/UID watermarks;
- polling and optional IDLE;
- message envelope extraction;
- body safe extraction;
- attachment handoff;
- DLP/secret checks;
- source manifests.

### Track 3. Extraction packet and handoff

Implement shared extraction output:

- parsed source text;
- entities/relations/claims;
- analytics facts;
- memory deltas;
- fingerprints;
- source refs;
- provenance.

### Track 4. Dedup and provenance

Implement registry for:

- source identity;
- raw and normalized hashes;
- attachment hashes;
- near-duplicate fingerprints;
- semantic claim hashes;
- business keys;
- duplicate candidates and version clusters.

### Track 5. Analytics storage and metrics

Implement:

- `data/analytics/` layout;
- Parquet writing;
- DuckDB query helpers;
- metrics calculation;
- monitor evaluation;
- signal creation;
- sample manifests.

### Track 6. Knowledge reflection and metric candidates

Implement:

- reflection over KnowledgeDelta and AnalyticsFactDelta;
- repeated pattern detection;
- candidate metric proposals;
- review queue;
- memory candidate handoff.

### Track 7. Optional DMS connector

Implement:

- DMS connector interface;
- CMIS/vendor API adapter slot;
- document metadata sync;
- workflow event sync;
- version/status handling;
- DMS-to-email/file dedup.

### Track 8. AI diagnostics and workflow routing

Implement:

- evidence packet builder;
- diagnostic playbooks;
- action permission policy;
- workflow routes;
- audit trail;
- dry-run mode.

## Definition of Ready

- ADR accepted or explicitly approved for implementation.
- First pilot source selected: mailbox/report/DMS collection.
- Data owner approves email content analysis.
- Scope and retention rules are documented.
- Dedup authority order is configured.
- Workflow owner confirms allowed AI actions.
- Verification commands are defined.

## Definition of Done

- Contracts and schemas validate.
- IMAP source can dry-run sync without storing credentials in repo.
- Extraction packet feeds both memory and analytics.
- Duplicate email/file/DMS report creates one canonical content cluster with multiple evidence refs.
- Metrics recalculate from analytics facts.
- Reflection proposes metric candidates.
- AI diagnostics run in dry-run mode with audited evidence.
- Docs and `PROJECT_STRUCTURE.yaml` are updated.

## Verification

Expected commands after implementation:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py makemigrations --check --dry-run
python manage.py test apps.analytics.tests apps.memory.tests apps.core.tests
python manage.py analytics_sync_source --source-code <code> --dry-run
python manage.py analytics_extract_source --source-code <code> --dry-run
python manage.py analytics_dedup_source --source-code <code> --dry-run
python manage.py analytics_recalculate_metrics --dry-run
python manage.py analytics_reflect_knowledge --dry-run
```

## Open Implementation Questions

- First production pilot mailbox and owner.
- Exact retention durations for raw EML, normalized text and facts.
- Which DMS product, if any, must be supported first.
- Whether RabbitMQ is available in the first deployment environment.
- Which AI actions are allowed without human confirmation.
