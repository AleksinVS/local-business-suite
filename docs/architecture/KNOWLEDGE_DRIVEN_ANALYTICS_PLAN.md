# План: knowledge-driven business analytics

Статус: архитектурный план; MVP control-plane, contracts, fixture-first IMAP sync, extraction packets, dedup candidates, metrics, signals, reflection and diagnostic commands implemented 2026-05-21.

Дата: 2026-05-21.

Связанный ADR: `docs/adr/ADR-0008-knowledge-driven-business-analytics.md`.

Связанные документы:

- `docs/architecture/ANALYTICS_MODEL.md`;
- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- `docs/adr/ADR-0006-external-system-knowledge-connectors.md`;
- `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md`;
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`;
- `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_PLAN.md`.

## Назначение

Этот документ описывает универсальную архитектуру непрерывной бизнес-аналитики, построенной вокруг знаний, электронной почты, документов и системы памяти.

Система аналитики не должна быть только слоем dashboard/report UI. Она должна:

- непрерывно получать новые знания;
- анализировать содержимое писем, отчетов, документов, чатов и memory graph;
- превращать извлеченные знания в аналитические факты;
- пересчитывать метрики;
- искать новые закономерности;
- предлагать новые показатели;
- выявлять отклонения;
- запускать AI-диагностику и бизнес-workflow.

Deployment-specific источники вроде Mango Office, Bitrix24, МИС, ERP или тикет-систем подключаются как слой обогащения и исходов. Они не являются фундаментом архитектуры.

## Архитектурная рамка

Базовый контур:

```text
Memory items / graph facts
Email contents over IMAP
Documents / file shares / optional DMS
Chats / user confirmed memory
External API enrichments

  -> source adapters
  -> DLP / scope gate
  -> parse / normalize
  -> ExtractionPacket
  -> KnowledgeDelta
  -> AnalyticsFactDelta
  -> metric dependency invalidation
  -> metric recalculation
  -> reflection and pattern mining
  -> signals and deviations
  -> AI diagnostics
  -> workflow routing
  -> memory candidates / metric candidates
```

Главный принцип: **extract once, derive many**. Один источник проходит DLP, парсинг и извлечение один раз, а результат используется и для памяти, и для аналитики.

## Разделение универсального ядра и deployment-профиля

Универсальное ядро содержит:

- source adapter contract;
- extraction packet schema;
- knowledge delta schema;
- analytics fact schema;
- analysis scope rules;
- metric/monitor contracts;
- dedup/provenance registry;
- AI diagnostic playbooks;
- workflow routes;
- storage layout;
- audit and access policies.

Deployment-профиль содержит:

- конкретные mailbox accounts;
- конкретные DMS/file-share источники;
- конкретные внешние API;
- mapping внешних пользователей/подразделений в `scope_tokens`;
- deployment-specific metrics;
- workflow routes;
- retention overrides;
- credentials and host-specific settings outside the main repo.

Например, MedEx является deployment-профилем поверх общего ядра:

```text
deployments/MedEx/
  mailboxes
  Mango Office
  Bitrix24
  Renovatio
  call-center metrics
  regulator correspondence metrics
```

## Источники первого уровня

### Memory

Memory остается управляемым источником знаний:

- `MemoryKnowledgeItem`;
- `MemoryGraphEntity`;
- `MemoryGraphFact`;
- memory chunks;
- organization candidates;
- chat-derived memory;
- external connector snapshots.

Новое или измененное знание создает `KnowledgeDelta`. Этот delta должен использоваться для аналитики так же, как email/document/API events.

Примеры аналитики из памяти:

- частота упоминаний проблемы в разных источниках;
- повторяющиеся причины отклонений;
- новые сущности и связи;
- знания, которые часто нужны пользователям, но отсутствуют в памяти;
- факты, влияющие на бизнес-метрики;
- противоречивые сведения о сроках, ответственных или статусах.

### Email over IMAP

IMAP является базовым email adapter. Microsoft 365 и Google Workspace могут быть добавлены как enhanced adapters, но универсальная архитектура должна работать без них.

Email ingestion анализирует содержимое писем, а не только факт доставки. Это важно для:

- отчетов заведующих отделениями;
- запросов регулирующих органов;
- ответов на запросы;
- жалоб;
- обязательств;
- поручений;
- согласований;
- уведомлений о рисках;
- регулярных сводок.

Минимальные email identity fields:

- mailbox code;
- folder;
- `UIDVALIDITY`;
- `UID`;
- `Message-ID`;
- `In-Reply-To`;
- `References`;
- sender and recipients;
- sent/received timestamps;
- subject;
- content hash;
- body hash;
- attachment hashes;
- thread id computed by the platform;
- source watermark.

IMAP IDLE можно использовать, если сервер поддерживает capability. Иначе используется scheduled polling.

### Documents and File Shares

Существующий document ingestion остается источником для файлов:

- dedicated read-only folder;
- UNC path;
- local folder;
- controlled parser/OCR cascade;
- safe corpus;
- graph extraction.

Для analytics loop каждый документ также может создавать `AnalyticsFactDelta`, если extraction profile это разрешает.

### Optional DMS

Если в организации уже есть система документооборота, она должна быть source of truth для:

- document id;
- version;
- registration number;
- author/owner;
- approval workflow;
- legal status;
- retention;
- file content pointer;
- access control metadata.

Предпочтительный порядок интеграции:

1. CMIS.
2. Vendor REST API.
3. Microsoft Graph / SharePoint delta for SharePoint-based DMS.
4. Read-only SQL bridge with owner approval.
5. Export folder as fallback.

DMS connector должен поставлять metadata, workflow events и content references. Он не должен обходить memory DLP, parser policies or analytics scope rules.

## Source Adapters

Единый adapter contract:

```text
discover
sync
fetch
normalize
extract
handoff_to_memory
handoff_to_analytics
reconcile_deletes
cleanup
```

Adapter output:

```json
{
  "schema_version": "source-envelope-v1",
  "source_code": "department_reports_mailbox",
  "source_kind": "email_imap",
  "external_id": "mailbox:INBOX:uidvalidity:uid",
  "operation": "upsert",
  "source_updated_at": "2026-05-21T10:00:00+03:00",
  "content_refs": [],
  "payload": {},
  "scope_tokens": ["org:default"],
  "sensitivity": "confidential",
  "retention_class": "email_normalized_default",
  "provenance": {
    "adapter": "imap",
    "run_id": "..."
  }
}
```

## ExtractionPacket

`ExtractionPacket` - единый результат анализа source item.

Состав:

- source identity;
- source references;
- raw hashes;
- normalized text;
- safe snippets;
- extracted entities;
- extracted relations;
- extracted claims;
- extracted business events;
- extracted metrics facts;
- attachment/document references;
- DLP findings;
- secret spans/handles;
- confidence;
- model/parser versions;
- provenance and lineage.

Пример:

```json
{
  "schema_version": "extraction-packet-v1",
  "source_identity": {
    "source_code": "department_reports_mailbox",
    "source_kind": "email_imap",
    "external_id": "mailbox:INBOX:3857529045:913"
  },
  "fingerprints": {
    "raw_sha256": "sha256:...",
    "normalized_text_sha256": "sha256:...",
    "simhash": "64bit:...",
    "semantic_claim_hashes": ["claim:..."]
  },
  "safe_text": "Отчет заведующего: за неделю 6 отмен...",
  "entities": [],
  "claims": [],
  "business_facts": [],
  "scope_tokens": ["department:therapy"],
  "sensitivity": "confidential",
  "provenance": {
    "parser_version": "email-parser-v1",
    "extractor_version": "knowledge-analytics-extractor-v1"
  }
}
```

## KnowledgeDelta

`KnowledgeDelta` описывает изменения в памяти/графе:

- new fact;
- updated fact;
- superseded fact;
- conflict;
- deleted source evidence;
- candidate only;
- low-confidence item;
- forbidden scope item.

KnowledgeDelta не обязан немедленно публиковать знание в organization memory. Он может создать candidate или review item.

## AnalyticsFactDelta

`AnalyticsFactDelta` - аналитическое представление извлеченного знания.

Примеры:

- `department_report_received`;
- `department_issue_reported`;
- `regulator_request_received`;
- `regulator_response_sent`;
- `deadline_committed`;
- `deadline_missed`;
- `complaint_received`;
- `service_capacity_issue_reported`;
- `risk_mentioned`;
- `document_approval_delayed`.

Пример:

```json
{
  "fact_type": "regulator_request_received",
  "event_time": "2026-05-21T09:30:00+03:00",
  "dimensions": {
    "regulator": "roszdravnadzor",
    "department": "diagnostics",
    "topic": "ultrasound_reports"
  },
  "measures": {
    "requested_documents": 12,
    "deadline_days": 5
  },
  "evidence_refs": ["email:..."],
  "scope_tokens": ["org:default", "department:diagnostics"],
  "sensitivity": "confidential"
}
```

## Business Analytics From Knowledge

Метрики пересчитываются не только из внешних API, но и из новых знаний.

Примеры:

### Отчеты заведующих отделениями

Метрики:

- received reports count;
- missing reports;
- reports with risks;
- repeated issue count by department;
- issue aging;
- staffing/capacity/equipment issue frequency;
- commitments created from reports;
- commitments completed.

Сигналы:

- отчет не получен до дедлайна;
- одна проблема повторяется N недель;
- отделение сообщает о росте отмен/дефицита ресурсов;
- в отчете есть высокий риск без назначенного действия.

### Запросы регуляторов и ответы

Метрики:

- incoming regulator requests;
- response SLA;
- open requests;
- overdue responses;
- requests by topic/regulator/department;
- repeated topics;
- missing evidence package;
- escalated cases.

Сигналы:

- запрос без ответственного;
- дедлайн ответа ближе порога;
- просрочка;
- повторяющийся запрос по одной теме;
- неполный пакет документов.

## Metric Reflection

Reflection jobs анализируют KnowledgeDelta и AnalyticsFactDelta:

- какие темы растут;
- какие сущности часто связаны с отклонениями;
- какие вопросы пользователи часто задают в chat/analytics;
- какие facts регулярно попадают в diagnostics;
- какие повторяющиеся события не покрыты метрикой;
- какие метрики редко используются или шумят.

Результат:

- `MetricCandidate`;
- `MonitorCandidate`;
- `KnowledgeCandidate`;
- `DiagnosticPlaybookCandidate`.

Новые метрики не активируются автоматически. Их утверждает владелец аналитики/процесса.

## Analysis Scope Rules

Анализируемая выборка задается правилами до AI processing.

Пример:

```json
{
  "code": "regulator_requests_daily",
  "title": "Daily regulator request analysis",
  "sources": ["email", "dms", "memory"],
  "include": {
    "mailboxes": ["regulatory"],
    "folders": ["INBOX", "Sent"],
    "dms_collections": ["outgoing_regulator_responses"],
    "memory_entity_types": ["RegulatorRequest", "RegulatorResponse"],
    "time_window": "now-24h"
  },
  "exclude": {
    "sensitivity": ["secret"],
    "mailboxes": ["personal_private"]
  },
  "limits": {
    "max_source_items": 1000,
    "max_threads": 250,
    "max_tokens_per_item": 6000
  },
  "sampling": {
    "strategy": "top_risk",
    "fallback": "latest"
  },
  "requires_audit": true
}
```

Strategies:

- `all`;
- `latest`;
- `top_risk`;
- `stratified`;
- `random`;
- `changed_since_watermark`;
- `graph_neighborhood`;
- `signal_evidence_window`.

Every analysis run writes a `SampleManifest`.

## Cross-source Deduplication

Same content can arrive through:

- email body;
- email attachment;
- file share;
- DMS document;
- chat paste;
- external API note.

Dedup must run at four levels.

### Level 1. Source idempotency

Purpose: avoid processing the same source item twice.

Keys:

- IMAP: mailbox, folder, `UIDVALIDITY`, `UID`;
- email identity: `Message-ID`;
- DMS: repository id, object id, version id;
- file share: source code, stable object id/path, content hash, mtime;
- API: source code, object type, external id, source version.

### Level 2. Exact content dedup

Purpose: detect byte-identical content.

Keys:

- raw SHA-256;
- attachment SHA-256;
- extracted file SHA-256.

If exact content matches, create a new evidence pointer to the canonical content object.

### Level 3. Normalized near-duplicate dedup

Purpose: detect same report with changed formatting, email quote, OCR noise or exported file format.

Keys:

- normalized text SHA-256;
- SimHash or MinHash;
- title/report period/department/document number;
- extracted business keys.

Near-duplicates create a duplicate candidate or version cluster. They are not automatically collapsed if business keys indicate a new version.

### Level 4. Semantic claim dedup

Purpose: avoid duplicating knowledge facts.

Keys:

- normalized subject;
- predicate;
- object/value;
- time interval;
- qualifiers;
- source confidence;
- canonical entity ids.

One semantic fact can point to many evidence refs.

Example:

```text
Fact:
  department:therapy reported issue staff_shortage for week 2026-W20

Evidence:
  email body from заведующий
  attached DOCX report
  DMS registered report
```

The fact is one. Evidence refs are many.

## Duplicate vs New Version

Do not collapse content when:

- document version differs;
- period differs;
- regulator request id differs;
- signed/approved status differs;
- DMS registration number differs;
- semantic claim differs;
- updated values supersede old values.

Instead, create version chain:

```text
ContentCluster
  -> version 1 evidence
  -> version 2 evidence
  -> current canonical evidence
```

Suggested authority preference:

1. DMS registered/signed document.
2. DMS approved draft.
3. Email attachment from official mailbox.
4. Email body.
5. File share copy.
6. Chat paste.

Authority preference does not delete other evidence. It selects canonical citation and version owner.

## Storage Layout

Runtime data:

```text
data/analytics/
  raw/
    email/
    dms/
    memory/
    external_api/
  normalized/
    email_threads/
    documents/
    business_facts/
    extraction_packets/
  marts/
    department_reports/
    regulator_requests/
    issues/
    metrics/
  incidents/
    signals/
    diagnostics/
  lineage/
    sample_manifests/
    run_events/
  dedup/
    content_fingerprints/
    duplicate_candidates/
```

Memory runtime stays under `data/memory/`.

Raw email/document payloads are disabled by default or stored only under explicit retention/quarantine policy. Normalized safe text and analytical facts can be retained according to the source contract.

## Django Control Plane Models

Future implementation candidates:

- `AnalyticsSource`;
- `AnalyticsExtractionRun`;
- `AnalyticsExtractionPacket`;
- `AnalyticsContentObject`;
- `AnalyticsEvidenceRef`;
- `AnalyticsDuplicateCandidate`;
- `AnalyticsFact`;
- `AnalyticsMetricDefinition`;
- `AnalyticsMetricSnapshot`;
- `AnalyticsMonitor`;
- `AnalyticsSignal`;
- `AnalyticsDiagnosticRun`;
- `AnalyticsCase`;
- `AnalyticsMetricCandidate`;
- `AnalyticsSampleManifest`;
- `AnalyticsAccessAudit`.

Django DB stores control-plane metadata, status, audit and workflow state. Bulk analytical facts and time series live in Parquet/DuckDB.

## Queueing

MVP can run with a simple backend in development, but production-like knowledge analytics requires durable queues:

- source sync;
- parse/extract;
- dedup/provenance;
- memory handoff;
- analytics fact materialization;
- metric recalculation;
- reflection;
- diagnostics;
- workflow actions.

RabbitMQ + Celery is the preferred production MVP direction for this analytics loop because jobs have different priorities, retries, delays and dead-letter needs.

Queue classes:

- `analytics.source_sync`;
- `analytics.extract`;
- `analytics.dedup`;
- `analytics.memory_handoff`;
- `analytics.fact_materialize`;
- `analytics.metrics`;
- `analytics.reflection`;
- `analytics.diagnostics`;
- `analytics.actions`;
- `analytics.dead_letter`.

## Access Control

Access is scope-token based and enforced before analysis and retrieval:

- source-level access;
- mailbox/folder access;
- DMS collection access;
- graph entity/fact access;
- analytical mart access;
- signal/case access;
- AI diagnostic evidence access.

AI agents receive only sampled evidence allowed by the workflow and actor scope. Sensitive fields are masked or replaced with handles before model calls.

## Review and Governance

Mandatory review:

- new metric candidates;
- new organization-wide knowledge derived from reflection;
- new diagnostic playbooks with autonomous actions;
- dedup conflict decisions for near-duplicates;
- source onboarding for production mailboxes/DMS;
- retention policy changes.

Optional review:

- routine exact duplicate merges;
- low-risk personal/team memory suggestions;
- metric recalculation from already-approved facts.

## MVP Vertical Slice

Recommended first universal MVP, independent of MedEx-specific telephony:

1. IMAP mailbox source.
2. Department head report extraction.
3. Regulator request/response extraction.
4. Cross-source dedup between email attachments and existing document ingestion.
5. Business facts in Parquet.
6. Metrics and monitors for received reports, open regulator requests and overdue responses.
7. AI diagnostics for high-risk requests and repeated department issues.
8. Memory candidates for confirmed patterns.

MedEx call-center analytics can be built on top as a deployment-specific extension.

## Contracts To Add

Future contract files:

```text
contracts/analytics/sources.json
contracts/analytics/analysis_scope_rules.json
contracts/analytics/business_facts.json
contracts/analytics/metrics.json
contracts/analytics/monitors.json
contracts/analytics/diagnostic_playbooks.json
contracts/analytics/workflow_routes.json
contracts/analytics/dedup_rules.json
contracts/analytics/retention_profiles.json
```

## Acceptance Criteria For Architecture Completion

- Email content analysis is supported through IMAP baseline.
- Memory deltas can materialize analytics facts.
- One extraction packet can feed memory and analytics.
- Duplicate reports across email, attachments, files and DMS are linked to one canonical content cluster.
- Analytics store is separate from memory and OLTP.
- Analysis scope rules are enforced before AI calls.
- Metric candidates can be created from reflection but require review before activation.
- DMS integration is optional and does not bypass document governance.

## References

- RFC 9051: IMAP4rev2 - https://www.rfc-editor.org/rfc/rfc9051.html
- RFC 2177: IMAP IDLE - https://www.rfc-editor.org/rfc/rfc2177.html
- RFC 5322: Internet Message Format - https://www.rfc-editor.org/rfc/rfc5322
- W3C PROV Overview - https://www.w3.org/TR/prov-overview/
- OpenLineage - https://openlineage.io/
- GraphRAG overview - https://microsoft.github.io/graphrag/index/overview/
- OASIS CMIS 1.1 - https://www.oasis-open.org/standard/cmisv1-1/
