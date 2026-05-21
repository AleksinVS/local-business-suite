# ADR-0008: Knowledge-driven business analytics

## Status

Proposed

## Date

2026-05-21

## Context

The existing analytics layer is documented as a Parquet/DuckDB/Evidence reporting path, while the memory service already supports governed ingestion, safe corpus, graph facts, chat-derived memory, reflection and external information system connectors. The next target architecture must make analytics a continuous business process rather than a user-requested dashboard.

The core requirement is not technical infrastructure monitoring. The system must continuously analyze business knowledge: memory facts, graph deltas, email contents, reports, regulatory correspondence, documents and, later, CRM/telephony/MIS/API context. New knowledge must update analytical facts and metrics, trigger deviations, launch AI diagnostics and route work into organization workflows.

Email is a first-class source. The baseline adapter is IMAP; Microsoft 365 and Google Workspace are optional enhanced adapters. The system must analyze email contents, not only delivery metadata. The same report can arrive by email and be stored in a file share or DMS, so duplicate and near-duplicate knowledge must be controlled across sources.

## Decision

Implement analytics as a **knowledge-driven business analytics control loop**:

```text
Knowledge sources
  -> governed extraction
  -> KnowledgeDelta
  -> AnalyticsFactDelta
  -> metric recalculation
  -> reflective pattern mining
  -> signal / deviation
  -> AI diagnostic workflow
  -> routed business action
  -> memory candidate / metric candidate
```

The baseline sources are:

- existing memory items and graph facts;
- IMAP mailboxes and email contents;
- documents from local/UNC folders and optional DMS connectors;
- chats and user-confirmed memory writes.

External APIs such as CRM, telephony, MIS, ERP and ticket systems are enrichment and outcome sources. They can become primary sources for a deployment, but the product architecture must not be tied to one implementation such as Mango Office or Bitrix24.

### Extract Once, Derive Many

Knowledge extraction and analytics extraction share the same source parse and DLP pass. A source item produces one extraction packet, and that packet can generate:

- memory chunks and graph facts;
- analytical facts;
- lineage/provenance records;
- metric invalidation events;
- reflection candidates;
- review items.

The expensive parsing and LLM/NLP extraction must not be repeated only because both memory and analytics need the result. Downstream metric recalculation, reflection and AI diagnostics remain asynchronous jobs so failures in analytics do not block ingestion of governed memory.

### Email-first Baseline

IMAP is the default mail adapter. Optional adapters may use Microsoft Graph or Gmail APIs when available, but the universal connector contract must work with IMAP:

- mailbox/folder identity;
- `UIDVALIDITY` and `UID`;
- `Message-ID`, `In-Reply-To` and `References`;
- envelope headers;
- safe body extraction;
- attachment handoff;
- flags and timestamps;
- watermarks and idempotency keys.

Email body text is analyzed when source policy allows it. The mail server remains the system of record unless an explicit archive mode is enabled.

### DMS Optional Integration

If an organization already has a document management system, the analytics/memory system must treat the DMS as the authoritative source for document identity, versions, workflow statuses, registration numbers and legal retention. Integration preference order:

1. CMIS if supported.
2. Vendor REST API.
3. Microsoft Graph / SharePoint delta API for SharePoint-based DMS.
4. Read-only SQL bridge only when officially supported by the DMS owner.
5. Export folder as a fallback.

### Cross-source Deduplication

Duplicate control is based on a provenance and fingerprint registry, not on a single source key. The system records multiple identities and fingerprints:

- source identity: mailbox/folder/UID, DMS document id/version, file path/inode, API object id;
- message identity: `Message-ID`, thread references, sent/received timestamps;
- byte hash: hash of raw payload or file content when available;
- normalized text hash: hash after parser cleanup, boilerplate removal and stable whitespace normalization;
- attachment hash: hash of each attachment payload;
- near-duplicate fingerprint: SimHash/MinHash or equivalent text fingerprint for almost-identical documents;
- semantic claim hash: stable hash of normalized extracted claim/fact;
- business key: document number, report period, department, regulator request id, patient-safe pseudonym or other domain key.

Exact duplicates are merged automatically at evidence level. Near-duplicates and conflicting versions create review items or version clusters. Knowledge facts are deduplicated at claim level: one fact can have many evidence pointers.

### Analytics Storage

Use separate analytical storage from operational and memory storage:

- Django DB remains the control plane for jobs, signals, diagnostics, cases, review state and audit.
- `data/analytics/` stores Parquet datasets for raw/normalized/mart layers.
- DuckDB is the embedded analytical query engine for MVP.
- `apps.memory` remains the governed knowledge store, graph, chunks, safe corpus and retrieval layer.

Some data belongs only to analytics and must not be written to memory: time-series metrics, intermediate aggregates, sampling manifests, processing features and low-level analytical facts that are not useful as durable knowledge.

### Scope Rules

Analysis must use declarative scope rules before AI processing. A scope rule defines sources, windows, mailboxes, DMS collections, graph entity types, sensitivity filters, scope tokens, sampling strategy and hard limits. Prompt-only filtering is not acceptable.

### Metric Discovery

Reflection jobs should propose new metrics when repeated knowledge patterns, user questions or diagnostic runs reveal a measurable business issue. New metrics are candidates requiring human review before activation.

## Alternatives Considered

### Dashboard-first analytics

Rejected as the target. Dashboards remain useful, but they do not continuously inspect new knowledge, detect deviations or trigger workflows.

### External API integrations as the foundation

Rejected as the universal foundation. CRM/telephony/MIS integrations are important, but the most portable baseline is memory + email + documents. API connectors should enrich this baseline.

### Store all email and documents inside memory

Rejected. This turns memory into an unmanaged archive and increases privacy/retention risk. Memory should store selected safe knowledge, evidence snippets, references, provenance and graph facts. Raw email and documents are source-owned or retained only under explicit archive/quarantine policy.

### Run separate extraction pipelines for memory and analytics

Rejected because it duplicates expensive parsing/LLM calls and can create inconsistent semantics. The accepted pattern is one extraction packet feeding both memory and analytics.

### Exact hash-only deduplication

Rejected as insufficient. The same report can appear as email body text, PDF attachment, DMS file and copied document with formatting changes. Exact hashes are necessary but not enough; normalized hashes, near-duplicate fingerprints and semantic claim hashes are also required.

## Consequences

### Positive

- Analytics becomes embedded in business processes rather than only visual reporting.
- Email and memory provide a universal baseline before deployment-specific integrations are ready.
- Extraction work is shared across memory and analytics.
- Duplicate reports across email, file storage and DMS can be merged while preserving evidence.
- Metrics can evolve from real knowledge patterns and user questions.
- The system keeps a path from a dashboard number back to source evidence and memory facts.

### Negative

- The architecture requires a dedicated analytics control plane, storage layout and queueing strategy.
- Cross-source deduplication is more complex than source-level idempotency.
- Email content analysis increases privacy, access-control and retention requirements.
- Metric candidates and organization-wide insights need review queues to avoid overfitting or false conclusions.

## Required Follow-up

- Create the architecture plan for knowledge-driven business analytics.
- Add execution workflow packets for contracts, IMAP ingestion, DMS integration, dedup/provenance registry, analytics storage and AI diagnostic workflow.
- Add contracts for analysis scope rules, business event/fact schemas, metrics, monitors, diagnostic playbooks and workflow routes.
- Add deployment guides for IMAP mailboxes, DMS connectors and retention.
- Add security tests for forbidden-scope leakage and duplicate evidence handling before processing production mailboxes.

## Reference Practices

- RFC 9051 defines IMAP mailbox synchronization primitives such as UIDs and UIDVALIDITY.
- RFC 2177 defines IMAP IDLE for near-real-time mailbox update notifications.
- RFC 5322 defines email identification fields including `Message-ID`, `In-Reply-To` and `References`.
- W3C PROV models provenance through entities, activities and agents.
- OpenLineage provides a standard model for pipeline runs, jobs and datasets.
- Microsoft GraphRAG documents extraction of entities, relationships, claims and community reports from text.
- CMIS is an OASIS standard for interoperating with enterprise content management systems.
