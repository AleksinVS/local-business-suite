# План: ingestion-коннектор и bootstrapping схемы графа памяти

Статус: финальный архитектурный план; MVP discovery/ingestion/schema bootstrapping реализован 2026-05-20.

Дата: 2026-05-20.

Связанный ADR: `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`.

## Назначение

Этот документ фиксирует общую схему реализации ingestion-коннектора для корпоративных документов и процесса первоначального/рабочего сбора типов графа знаний.

План дополняет базовую архитектуру СоСНА из `docs/adr/ADR-0003-ai-memory-service.md` и `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md`. Он не заменяет ADR: решения зафиксированы в ADR-0004, а здесь описаны компоненты, порядок работ, проверки и границы реализации.

Текущий implementation status: в `apps.memory` добавлены `MemorySourceObject`, `MemoryIngestionRun`, `MemoryIngestionIssue`, `MemoryGraphSchemaProposal`, `MemoryGraphEntity`, `MemoryGraphExtractionRun`, `MemoryGraphReviewItem`, команды `memory_discover_source`, `memory_ingest_source`, `memory_prepare_bootstrap_package`, `memory_graph_schema_discover`, `memory_graph_extract`, контракты `memory_ingestion_profiles.json` и `memory_graph_schema.json`. Production parser/OCR backend для PDF/Office/scans остается отдельным следующим этапом.

Дополнение 2026-05-22: после перехода к файловым знаниям ingestion больше не создает постоянный слой `MemorySnapshot`/`MemoryChunk`. Для поиска создается `MemorySearchDocument`, а временные обработанные файлы остаются только в processing-зоне и удаляются по регламенту. Разделы ниже, где описаны safe corpus/chunks, являются исторической частью плана и заменяются целевой схемой из `docs/architecture/MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md`.

## Принятые решения

- Первое внедрение: Windows Server в домене Active Directory.
- Источники документов на первом этапе: локальная папка на сервере или Windows SMB share через UNC path.
- Для первого корпуса создается отдельная read-only папка "документы для памяти"; общий корпоративный файловый хаос не сканируется.
- Целевой production-вариант учетной записи: gMSA. Допустимый стартовый вариант: обычный доменный service account с read-only правами.
- Mapped drives не использовать. Для сервисов использовать UNC paths вида `\\SERVER\Share\Folder`.
- Форматы: PDF, DOC, DOCX, XLS, XLSX, scanned PDF, standalone images.
- OCR языки: `rus+eng`.
- Картинки, встроенные внутрь DOCX/PDF, на первом этапе не индексируются как отдельный источник, если документ не является сканом.
- GLM-OCR допустим для тестов на подготовленной выборке без чувствительных данных. В production его нужно прорабатывать как будущий отдельный local GPU OCR service.
- Raw-документы по умолчанию не копируются в `data/memory/raw_vault/`; хранится только ссылка, hash и metadata.
- Допустимые будущие raw modes: `quarantine_copy`, `immutable_raw_vault`.
- Password-protected/encrypted документы пропускаются и попадают в audit/review очередь.
- Default max file size: 100 MB.
- Partial indexing обязателен: большие/сложные документы могут индексироваться частично с review flag.
- ClamAV/antivirus gate на первом этапе опционален, но интерфейс нужно предусмотреть.
- На первом этапе права доступа задаются через `scope_rule` из `MemorySource`; наследование ACL проектируется интерфейсом для следующего этапа.
- Схема графа единая для организации как минимум на первом этапе.
- Первоначальное определение типов графа идет по подразделениям, последовательно выбирая процессно разные отделения.
- Профильный эксперт отделения утверждает schema delta; финальное принятие у владельца графа.
- Competency questions определяются отдельным этапом перед bootstrapping конкретного отделения.
- Инициация считается достаточной после обработки всего первоначального корпуса.
- Конфликты терминов между отделениями решают профильный эксперт и владелец графа.
- Rejected schema proposals хранятся как negative examples.
- Конкретные `GraphEntity` и `GraphFact` после утверждения схемы создаются автоматически; обязательной review-очереди для каждого instance нет.
- Review UI нужен выборочно: для схемы, ошибок ingestion, partial документов и рискованных/спорных extraction cases.

## Общая схема

```text
MemorySource contract
  -> local_path / unc_path adapter
  -> discovery state
  -> file stability check
  -> MIME/type/limit/security checks
  -> parser/OCR cascade
  -> normalized document blocks
  -> PII/secret gate
  -> safe corpus
  -> chunks
  -> graph schema bootstrapping or graph instance extraction
  -> full-text/vector/graph indexes
  -> memory.search with citations
  -> audit/eval/review queues
```

Graph schema bootstrapping:

```text
curated department corpus
  -> safe/de-identified bootstrap package
  -> expensive schema discovery
  -> schema type/relation/attribute proposals
  -> department expert review
  -> graph owner approval
  -> contracts/ai/memory_graph_schema.json
```

Working graph process:

```text
new or changed safe documents
  -> cheap local extraction by accepted schema
  -> automatic GraphEntity/GraphFact write
  -> exception review only
  -> statistics for future schema proposals
```

## Source Storage

### Supported first adapters

`local_path`:

- reads a local directory on the Windows Server;
- useful for the dedicated read-only memory corpus folder;
- also works when SMB is mounted or synced externally.

`unc_path`:

- reads Windows SMB share paths such as `\\SERVER\Share\Folder`;
- uses the Windows service account identity;
- avoids mapped drive visibility issues in Windows services.

### Future adapters

- direct SMB client;
- WebDAV/Nextcloud;
- SharePoint/OneDrive through Microsoft Graph;
- S3-compatible object storage;
- DMS-specific adapter.

These are not first-stage requirements.

## Service Account Model

Recommended path:

1. Start with `DOMAIN\svc_memory_ingest` if gMSA is not available.
2. Give read-only access to the dedicated memory document folder.
3. Run Django/ingestion worker under that account or ensure the worker process can access the UNC path.
4. Move to gMSA (`DOMAIN\gmsa-memory$`) for production hardening.

Design implications:

- credentials must not be stored in `contracts/`;
- service account choice affects audit on file server;
- read-only permissions reduce ingestion blast radius;
- future ACL resolver can inspect source ACLs only if the service account can read them.

## Discovery State

Add a durable discovery layer before `MemorySnapshot`.

Proposed model: `MemorySourceObject`.

Key fields:

- `source`;
- `object_id`;
- `object_uri`;
- `relative_path`;
- `file_name`;
- `extension`;
- `mime_type`;
- `size_bytes`;
- `mtime`;
- `content_hash`;
- `etag_or_inode`;
- `last_seen_at`;
- `last_stable_at`;
- `discovery_status`;
- `ingestion_status`;
- `last_ingested_at`;
- `failure_count`;
- `last_error`;
- `partial_reason`;
- `acl_fingerprint`;
- `metadata`.

Why this is needed:

- thousands of files require idempotent discovery;
- deleted files must be detected without losing old provenance;
- modified files must create new snapshots, not overwrite history;
- transient parser/OCR failures need retry state;
- partial and encrypted documents must be visible to operators.

## Ingestion Runs and Queues

Use `MemoryIndexJob` where it fits, but add more specific records if needed:

- `MemoryIngestionRun` for a source-level scan/import run;
- `MemoryIngestionIssue` for failed, skipped, encrypted, oversized, partial or suspicious documents;
- `MemoryGraphSchemaProposal` for schema-level proposals;
- `MemoryGraphExtractionRun` for graph extraction metrics and provenance.

Issue statuses:

```text
open
acknowledged
needs_expert_review
resolved
ignored
```

Issue kinds:

```text
encrypted_file
unsupported_format
file_too_large
partial_indexed
parser_timeout
ocr_timeout
pii_blocked
secret_blocked
acl_unresolved
schema_unknown_type
schema_unknown_relation
canonicalization_conflict
```

## Parser and OCR Cascade

The connector must not depend on one parser.

Recommended cascade:

1. Native parser for text-like formats: TXT, Markdown, HTML, CSV.
2. Docling-compatible parser for PDF, DOCX, XLSX and structured document output.
3. Apache Tika or LibreOffice conversion fallback for legacy DOC/XLS.
4. OCR backend for scanned PDFs and standalone image files.
5. Quarantine/review issue if no safe extraction path works.

OCR backend interface:

```text
Tesseract/OCRmyPDF local backend
GLM-OCR cloud test backend
GLM-OCR local GPU service backend
```

GLM-OCR policy:

- cloud mode only for a specially prepared pseudonymized or non-sensitive test corpus;
- production mode should be local and service-isolated;
- OCR output is treated as untrusted extracted text until it passes PII/secret gates.

## Limits and Partial Indexing

Default limits:

- `max_file_size_mb`: 100;
- OCR languages: `rus+eng`;
- parser timeout: implementation-defined, but must be configurable;
- OCR timeout: implementation-defined, but must be configurable;
- Excel cell/sheet limits: determined during test exploitation with real workbooks.

Partial indexing behavior:

- create safe chunks for processed parts;
- set partial flag and reason;
- create `MemoryIngestionIssue`;
- include partial status in metadata/citations;
- never present partial output as complete document coverage.

Excel policy:

- attempt full extraction across sheets;
- preserve workbook/sheet/table provenance;
- for oversized workbooks, index a bounded subset and flag `partial_indexed`;
- use tests to decide final cell/sheet/page limits.

## Privacy and Cloud Bootstrap Package

Cloud-init is allowed only for a prepared package.

Allowed after preparation:

- departments/subdivisions;
- employee names only after pseudonymization or explicit approval for the test corpus;
- internal document numbers only after policy review or pseudonymization where needed.

Always remove or block:

- passwords;
- tokens;
- API keys;
- private keys;
- connection strings;
- patient data;
- secrets in screenshots or OCR output;
- unreviewed sensitive data.

Preparation pipeline:

```text
raw document reference
  -> local parsing/OCR
  -> normalized blocks
  -> PII/secret scan
  -> stable pseudonymization
  -> human approval for export package
  -> cloud schema discovery/OCR test
```

The package must preserve analytical structure:

- document id;
- section heading;
- page/sheet/table coordinates;
- stable block hash;
- pseudonym consistency within the package;
- source category and department tag.

## Graph Schema Contract

Create `contracts/ai/memory_graph_schema.json`.

The contract should include:

- `schema_version`;
- entity types;
- relation types;
- attribute types;
- allowed subject/object type pairs;
- canonicalization rules;
- aliases and labels;
- negative examples;
- forbidden/noisy types;
- confidence thresholds;
- auto-accept policy;
- review policy;
- department evidence;
- changelog.

Example entity type shape:

```json
{
  "code": "Department",
  "label": "Подразделение",
  "description": "Организационная единица, участвующая в процессах учреждения.",
  "scope_note": "Используется для отделений, отделов и служб.",
  "positive_examples": ["Отдел медицинской техники"],
  "negative_examples": ["кабинет", "здание"],
  "attributes": ["name", "short_name"],
  "status": "accepted"
}
```

Example relation type shape:

```json
{
  "code": "department_responsible_for_procedure",
  "label": "подразделение отвечает за процедуру",
  "subject_type": "Department",
  "object_type": "Procedure",
  "description": "Подразделение отвечает за выполнение или контроль процедуры.",
  "status": "accepted"
}
```

## Bootstrapping Types By Departments

### Stage A. Initiation

Goal: create the first unified graph schema.

Process:

1. Choose a process-diverse department.
2. Prepare a curated document subset for that department.
3. Define competency questions for that department.
4. Build a safe/de-identified schema discovery package.
5. Run expensive discovery:
   - local small models;
   - optional cloud model on approved safe package;
   - clustering of repeated terms and relation patterns.
6. Produce proposals:
   - entity type proposals;
   - relation type proposals;
   - attribute proposals;
   - canonicalization rule proposals;
   - forbidden/noisy pattern proposals.
7. Profile expert reviews the department schema delta.
8. Graph owner accepts, edits or rejects the delta.
9. Store accepted proposals in `memory_graph_schema.json`.
10. Store rejected proposals as negative examples.
11. Repeat for the next process-diverse department.

Completion criterion:

- the initial document corpus has been processed;
- accepted schema is sufficient for agreed competency questions;
- rejected/noisy proposals are stored;
- extraction eval cases exist for accepted types and relations.

### Stage B. Working Schema Evolution

Goal: keep the schema useful without expensive constant analysis.

Process:

1. New/changed documents are ingested normally.
2. Local cheap extractors use the accepted schema.
3. Valid GraphEntity/GraphFact instances are created automatically.
4. Unknown patterns are not added to the graph schema immediately.
5. Statistics are collected:
   - frequent unknown entity-like spans;
   - repeated relation-like patterns;
   - extraction conflicts;
   - terms rejected by experts;
   - department/process coverage gaps.
6. Periodically create schema proposals from statistics.
7. Route proposals to profile experts and graph owner.
8. Version `memory_graph_schema.json` after acceptance.

## Graph Instance Extraction

After schema acceptance, the instance process should be automatic.

Proposed records:

- `MemoryGraphEntity`: canonical graph node;
- `MemoryGraphFact`: accepted relation/fact with provenance;
- `MemoryGraphExtractionRun`: extraction run metadata and metrics;
- `MemoryGraphReviewItem`: only for exceptions.

No mandatory per-instance candidate queue:

- high-confidence valid entities/facts are accepted automatically;
- review is required only for exceptions;
- rejected extraction exceptions are kept as training/eval feedback.

Validation gates before automatic write:

- type exists in `memory_graph_schema.json`;
- relation exists and subject/object type pair is allowed;
- evidence is attached to safe chunk/block;
- confidence threshold is met;
- no PII/secret warning;
- scope/sensitivity are inherited from source/snapshot/chunk;
- canonicalization is not ambiguous;
- no unresolved conflict with an existing fact.

## Review UI

Django Admin is acceptable for low-volume operator inspection, but a selective user-facing review UI is required for profile experts.

First UI scope:

- schema proposals;
- accepted/rejected proposal history;
- ingestion issues;
- partial documents;
- encrypted/skipped documents;
- graph extraction exceptions;
- conflict resolution.

Not in first UI scope:

- review of every accepted entity/fact;
- visual graph explorer;
- full ontology editor.

## Contracts To Add Or Extend

Required:

- `contracts/ai/memory_graph_schema.json`;
- `contracts/schemas/memory_graph_schema.schema.json`;
- source/ingestion profile contract changes for adapter, parser/OCR, limits, raw storage mode and ACL mode.

Recommended split:

- keep `memory_sources.json` focused on source identity, ownership, scope, sensitivity and source reference;
- add `memory_ingestion_profiles.json` for adapter/parser/OCR/limits;
- add `memory_graph_schema.json` for graph schema.

This split avoids turning `memory_sources.json` into a large operational profile document.

## Implementation Tracks

### Track 1. ADR and Contracts

Deliverables:

- ADR-0004;
- `MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`;
- `memory_graph_schema.json`;
- JSON Schema validators;
- runtime copy support in settings;
- `validate_architecture_contracts` checks.

Acceptance:

- contracts validate;
- runtime copy is created under `data/contracts/ai/`;
- invalid relation subject/object pairs are rejected.

### Track 2. Discovery State and Ingestion Issues

Deliverables:

- `MemorySourceObject`;
- `MemoryIngestionRun` or equivalent run tracking;
- `MemoryIngestionIssue`;
- admin views;
- migration and tests.

Acceptance:

- discovery can detect unchanged, changed, new and missing files;
- encrypted/oversized/unsupported files create issues;
- issue queue is visible in admin.

### Track 3. Local/UNC Storage Adapter

Deliverables:

- storage adapter interface;
- local path adapter;
- UNC path support on Windows;
- path traversal and symlink safeguards;
- polling discovery with file stability checks.

Acceptance:

- no mapped drive dependency;
- read-only source is sufficient;
- discovery handles thousands of files incrementally.

### Track 4. Parser/OCR Pipeline

Deliverables:

- parser interface;
- parser cascade;
- OCR backend interface;
- Tesseract/OCRmyPDF local backend or documented placeholder;
- GLM-OCR cloud test profile behind explicit policy gate;
- parser/OCR timeout and size limits.

Acceptance:

- PDF/DOC/DOCX/XLS/XLSX/scans are handled or produce review issues;
- output is normalized into blocks with provenance;
- partial extraction is represented explicitly.

### Track 5. Privacy and Bootstrap Package

Deliverables:

- stable pseudonymization for bootstrap packages;
- stronger secret scanning for extracted text;
- export package format;
- human approval checkpoint before cloud-init.

Acceptance:

- secrets are blocked;
- patient data is blocked or pseudonymized according to policy;
- package preserves document/section/page/sheet provenance.

### Track 6. Graph Schema Bootstrapping

Deliverables:

- schema proposal model/service;
- department-tagged bootstrap workflow;
- expert review workflow;
- graph owner final approval;
- accepted/rejected proposal persistence;
- schema version updates.

Acceptance:

- proposals include evidence and examples;
- rejected proposals remain available as negative examples;
- schema changes are auditable.

### Track 7. Automatic Graph Instance Extraction

Deliverables:

- graph extractor interface;
- local model/pattern extractor baseline;
- optional small-model extractors for tests;
- `MemoryGraphEntity` if node registry is accepted;
- `MemoryGraphFact` schema-version/provenance extensions;
- exception-only review items.

Acceptance:

- accepted schema controls extraction;
- high-confidence valid facts are written automatically;
- unknown/conflicting/low-confidence items go to review instead of polluting graph.

### Track 8. Review UI and Operations

Deliverables:

- selective expert review UI;
- admin filters/actions for issues and schema proposals;
- metrics dashboard or admin summaries.

Acceptance:

- profile experts can approve/reject schema proposals;
- graph owner can finalize schema deltas;
- operators can find partial/skipped/encrypted documents.

### Track 9. Evaluation and Deployment Docs

Deliverables:

- Windows deployment guide for service account, UNC paths and read-only folders;
- smoke tests;
- leakage tests;
- graph schema eval cases;
- parser/OCR quality checklist.

Acceptance:

- `python manage.py validate_architecture_contracts` passes;
- ingestion dry-run shows planned changes without indexing;
- eval reports schema coverage, extraction precision, issue counts and leakage checks.

## Proposed Commands

```bash
python manage.py memory_discover_source --source-code <code> --dry-run
python manage.py memory_discover_source --source-code <code>
python manage.py memory_ingest_source --source-code <code> --dry-run
python manage.py memory_ingest_source --source-code <code>
python manage.py memory_prepare_bootstrap_package --source-code <code> --department <code>
python manage.py memory_graph_schema_discover --package <package-id>
python manage.py memory_graph_extract --source-code <code> --dry-run
```

Commands must write runtime artifacts only under `data/memory/`.

## Evaluation Metrics

Ingestion:

- discovered files;
- changed/new/deleted files;
- parser success rate;
- OCR success rate;
- encrypted/skipped count;
- partial indexed count;
- average processing time;
- issue backlog age.

Privacy/security:

- PII blocked/pseudonymized count;
- secret detection count;
- cloud package approval status;
- leakage regression result.

Graph schema:

- proposed type count;
- accepted/rejected type count;
- relation coverage;
- duplicate/merge rate;
- unknown pattern frequency;
- competency question coverage.

Graph instances:

- extracted entity count;
- extracted fact count;
- confidence distribution;
- conflict rate;
- review exception rate;
- citation/provenance completeness.

## Open Implementation Decisions

These are not architecture blockers:

- exact first departments for schema initiation;
- exact competency questions for each department;
- final parser library combination after real-document tests;
- Excel cell/sheet limits after test exploitation;
- first version of expert review UI scope;
- whether to add `memory_ingestion_profiles.json` immediately or extend `memory_sources.json` first.

## References

- W3C SKOS Primer: https://www.w3.org/TR/skos-primer/
- Stanford Ontology Development 101: https://protege.stanford.edu/publications/ontology_development/ontology101.pdf
- Microsoft GraphRAG documentation: https://github.com/microsoft/graphrag
- Microsoft gMSA documentation: https://learn.microsoft.com/en-us/windows-server/security/group-managed-service-accounts/group-managed-service-accounts-overview
- Microsoft UNC paths and file path formats: https://learn.microsoft.com/en-us/dotnet/standard/io/file-path-formats
- Docling documentation: https://docling-project.github.io/docling/
- Apache Tika documentation: https://tika.apache.org/
- OCRmyPDF documentation: https://ocrmypdf.readthedocs.io/
- Microsoft Presidio: https://microsoft.github.io/presidio/
