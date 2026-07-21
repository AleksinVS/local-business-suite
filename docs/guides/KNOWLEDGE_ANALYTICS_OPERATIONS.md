# Операционный guide: knowledge-driven business analytics

Статус: draft guide.

Дата: 2026-05-21.

Связанные документы:

- `docs/adr/ADR-0008-knowledge-driven-business-analytics.md`;
- `docs/architecture/KNOWLEDGE_DRIVEN_ANALYTICS_PLAN.md`;
- `docs/architecture/ANALYTICS_MODEL.md`;
- `docs/guides/MEMORY_INGESTION_OPERATIONS.md`.

## Назначение

Этот guide описывает практические правила подключения источников и эксплуатации контура бизнес-аналитики из знаний, электронной почты, документов и памяти.

## Source Onboarding Checklist

Для каждого источника нужно заполнить:

- business owner;
- technical owner;
- data owner;
- source kind: `memory`, `email_imap`, `file_share`, `dms`, `external_api`;
- какие данные анализируются;
- какие данные нельзя анализировать;
- какие поля являются чувствительными;
- scope mapping;
- retention;
- частота sync;
- допустимая задержка;
- правила дедупликации;
- какие метрики источник обновляет;
- какие workflow может запускать источник.

## IMAP Mailbox Intake

Минимальные вопросы для подключения mailbox:

1. Какой бизнес-процесс отражает mailbox?
2. Кто владелец mailbox?
3. Какие папки анализировать?
4. Какие папки исключить?
5. Анализировать входящие, исходящие или оба направления?
6. Можно ли анализировать body писем?
7. Можно ли анализировать вложения?
8. Какие типы вложений разрешены?
9. Нужно ли сохранять raw EML?
10. Какой retention для raw, normalized, facts и audit?
11. Кто видит письма, извлеченные факты, сигналы и диагностические пакеты?
12. Какие регулярные отчеты ожидаются в почте?
13. Какие внешние запросы или регуляторы встречаются?
14. Какие дедлайны и SLA важны?
15. Какие автоматические действия разрешены AI-agent workflow?

Baseline technical fields:

- IMAP host/port/TLS setting stored only in deployment config;
- mailbox code;
- folder allowlist/denylist;
- service account or delegated mailbox access;
- UIDVALIDITY/UID watermarks;
- poll interval or IDLE mode;
- attachment policy;
- DLP profile;
- parser profile.

## Email Content Analysis

Почтовый source анализирует содержимое письма, если это разрешено source policy:

- plain text body;
- HTML body after safe extraction;
- quoted text policy;
- signatures/footers removal;
- attachment text;
- structured tables in reports;
- dates/deadlines;
- commitments;
- requests and responses;
- sender role and organization;
- mentioned departments, services, patients/pseudonyms, regulators and documents.

Recommended extraction outputs:

- `EmailThread`;
- `EmailMessageEnvelope`;
- `EmailContentObject`;
- `EmailAttachmentRef`;
- `ExtractedClaim`;
- `BusinessFactDelta`;
- `KnowledgeDelta`;
- `DlpFinding`;
- `DedupFingerprint`.

## Report Examples

### Department Head Report

Expected extracted facts:

- report period;
- department;
- author;
- submitted_at;
- key risks;
- quantitative values;
- issues;
- commitments;
- requested help;
- attachments/evidence.

Analytics examples:

- reports received on time;
- missing reports;
- recurring issues;
- issues by department;
- commitments created;
- commitments overdue;
- high-risk report count.

### Regulator Request

Expected extracted facts:

- regulator;
- request number;
- received_at;
- deadline;
- requested documents;
- topic;
- responsible department;
- required response channel;
- severity;
- related DMS documents;
- response status.

Analytics examples:

- open regulator requests;
- overdue regulator responses;
- average response time;
- requests by topic;
- repeat topics;
- incomplete evidence packages;
- escalated requests.

## DMS Intake

If a DMS exists, ask:

1. What DMS product is used?
2. Does it support CMIS?
3. Does it have a documented REST API?
4. Does it expose version ids?
5. Does it expose registration numbers?
6. Does it expose approval workflow events?
7. Does it expose retention/legal status?
8. How are access rights represented?
9. Which collections/folders are in scope?
10. Which document types are in scope?
11. Can content be downloaded for parsing?
12. Should the system store only references?
13. What is the source of truth for final approved version?

DMS is preferred as canonical authority for registered documents. Email is often delivery evidence. File share copies are secondary unless explicitly declared authoritative.

## Dedup Operations

Deduplication should never silently delete evidence. It should link evidence to one canonical content cluster or create a review candidate.

### Exact Duplicate

Automatic merge is allowed when:

- raw content hash matches;
- or attachment hash matches;
- or DMS version id matches;
- and scope/sensitivity do not conflict.

Action:

- keep one canonical content object;
- add evidence reference;
- record source identity;
- preserve all provenance.

### Near Duplicate

Review or version clustering is required when:

- normalized text hash differs but SimHash/MinHash is near;
- document number matches but version differs;
- period differs;
- values differ;
- DMS approval status differs;
- source authority differs.

Action:

- create `DuplicateCandidate`;
- compute differences;
- suggest canonical authority;
- require review for collapse or version chain.

### Semantic Duplicate

Automatic fact-level merge is allowed only when:

- canonical subject id matches;
- predicate matches;
- object/value matches;
- time period matches;
- qualifiers match;
- source sensitivity permits merge.

Action:

- one knowledge fact;
- multiple evidence refs;
- confidence can be updated from corroboration count;
- contradictory evidence creates conflict/review item.

## Canonical Authority Rules

Default authority priority:

1. Registered/signed DMS document.
2. Approved DMS draft.
3. Official mailbox attachment.
4. Official mailbox body.
5. Controlled file-share document.
6. External API note.
7. Chat/user paste.

Deployment can override this order per source.

## Analysis Scope Rule Operations

Before creating or running an analysis scope:

- confirm business owner;
- confirm source allowlist;
- confirm exclusion rules;
- confirm sensitivity and scope tokens;
- set hard limits;
- set sampling strategy;
- define audit visibility;
- define output targets.

Never rely on prompt text as the only access-control boundary.

## Metric Candidate Review

Metric candidates can be proposed by:

- repeated user questions;
- repeated diagnostic findings;
- repeated email/DMS issues;
- new graph communities/topics;
- business owner request.

Review must answer:

- What decision will this metric support?
- Who owns it?
- How often does it update?
- Which sources feed it?
- What is the formula?
- What is the acceptable threshold?
- Which workflow starts on deviation?
- Is it safe to expose to each role?

## Retention Defaults

Suggested default classes:

| Layer | Default |
| --- | --- |
| raw EML / raw DMS payload | disabled or short-lived quarantine |
| normalized safe text | bounded reprocessing window |
| extracted facts | while analytics use is active |
| metric snapshots | per reporting requirement |
| evidence refs/provenance | longer audit retention |
| memory knowledge | while active or until superseded/deleted |
| duplicate fingerprints | long enough for dedup and replay |

Exact durations are deployment decisions.

## Incident Handling

Create an issue/review item when:

- source credentials fail;
- IMAP UIDVALIDITY changes unexpectedly;
- duplicate candidate has conflicting values;
- DLP finds forbidden data;
- parser cannot read an attachment;
- source scope mapping is missing;
- metric recalculation fails;
- AI diagnostic attempts forbidden evidence access;
- DMS version cannot be resolved.

## Smoke Checks

Future commands should cover:

```bash
python manage.py analytics_sync_source --source-code <code> --dry-run
python manage.py analytics_extract_source --source-code <code> --dry-run
python manage.py analytics_dedup_source --source-code <code> --dry-run
python manage.py analytics_recalculate_metrics --dry-run
python manage.py analytics_reflect_knowledge --dry-run
python manage.py analytics_run_diagnostic --signal-id <id> --dry-run
python manage.py validate_architecture_contracts
```

## Security Rules

- Do not commit mailbox credentials, IMAP hosts, DMS credentials or webhook URLs.
- Do not store raw email bodies by default.
- Do not store raw attachments outside the approved runtime area.
- Do not send sensitive email content to cloud AI unless sensitivity route explicitly permits it.
- Preserve provenance and source hashes for every extracted fact.
- Keep analytics access decisions auditable.

## References

- RFC 9051: IMAP4rev2 - https://www.rfc-editor.org/rfc/rfc9051.html
- RFC 2177: IMAP IDLE - https://www.rfc-editor.org/rfc/rfc2177.html
- RFC 5322: Internet Message Format - https://www.rfc-editor.org/rfc/rfc5322
- W3C PROV Overview - https://www.w3.org/TR/prov-overview/
- OpenLineage - https://openlineage.io/
- OASIS CMIS 1.1 - https://www.oasis-open.org/standard/cmisv1-1/
