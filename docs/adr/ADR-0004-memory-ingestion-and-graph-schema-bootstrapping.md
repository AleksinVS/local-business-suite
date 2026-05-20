# ADR-0004: Memory Ingestion Connector and Graph Schema Bootstrapping

## Status

Accepted

## Date

2026-05-20

## Context

ADR-0003 accepted the governance-first AI memory service architecture. The next architectural step is to ingest long-lived corporate documents into memory and use them to build a knowledge graph.

The first deployment target is Windows Server in an Active Directory domain. Corporate documents will initially live in a dedicated read-only document folder, either local to the server or exposed through a Windows SMB share. Later deployments should support additional storage adapters, but the first implementation must be reliable for local paths and UNC paths.

The memory system must support:

- thousands or tens of thousands of documents;
- PDF, DOC, DOCX, XLS, XLSX, scanned PDFs and image files;
- OCR languages `rus+eng`;
- partial indexing for large or difficult documents;
- a default file limit of 100 MB;
- optional future antivirus scanning;
- scope-based access in the first version, with ACL inheritance designed for a later stage;
- graph construction from safe text only;
- a moderated process for bootstrapping graph schema types, not a fully autonomous graph schema.

The graph schema bootstrapping process is intentionally separated from graph instance extraction:

- schema bootstrapping defines entity types, relation types, attributes, canonicalization rules and forbidden/noisy patterns;
- graph instance extraction creates concrete entities and facts after the schema has been accepted.

## Decision

Implement a first-class ingestion connector and graph schema bootstrapping workflow inside `apps.memory`, with replaceable adapters for storage, parsing, OCR and graph extraction.

### Storage and Runtime Access

- The first storage adapters are `local_path` and `unc_path`.
- SMB shares are accessed through UNC paths such as `\\SERVER\Share\Folder`, not mapped drives.
- The target production account model is a domain gMSA. A normal domain service account is acceptable for the first deployment if gMSA setup is not ready.
- The first source corpus should be a dedicated read-only folder prepared for memory ingestion, not the full unmanaged corporate share.
- Real storage ACL inheritance is deferred. MVP access uses `scope_rule` from `MemorySource`, while the adapter interface must expose future ACL metadata.

### Raw Document Handling

- Default raw mode is `reference_only`: store URI/path reference, content hash, metadata, MIME type, size and timestamps, but do not copy raw documents into `data/memory/`.
- `quarantine_copy` and `immutable_raw_vault` are permitted future modes, but they must be explicitly enabled and documented.
- Password-protected or encrypted files are skipped and written to a review/audit queue.

### Parsing and OCR

- Use a parser cascade rather than one parser:
  - native text/Markdown/HTML/CSV extraction where applicable;
  - Docling or equivalent structured parser for modern Office/PDF formats;
  - Apache Tika or LibreOffice conversion fallback for legacy DOC/XLS;
  - OCR backend for scanned PDFs and standalone image files.
- The initial OCR languages are `rus+eng`.
- Embedded images inside DOCX/PDF are not indexed in the first stage unless the whole document/page is handled as a scan.
- GLM-OCR is treated as an optional backend:
  - cloud GLM-OCR may be used only for a specially prepared non-sensitive or pseudonymized test corpus;
  - production GLM-OCR should be designed as a future local GPU OCR service, not embedded inside the main Django process.
- ClamAV or another antivirus scanner is optional for later stages, not a first-stage hard dependency.

### Limits and Partial Indexing

- Default maximum file size is 100 MB.
- Large documents are not simply rejected: they may be partially indexed, marked with a review flag and surfaced in the ingestion issue queue.
- Excel files should be indexed as completely as feasible, but large workbook limits and partial extraction behavior must be validated on real samples.
- Partial citations must preserve enough provenance to show that the document was indexed partially.

### Contracts

Add or extend contracts under `contracts/ai/`:

- `memory_graph_schema.json` is the authoritative graph schema contract.
- ingestion/source contracts must describe adapter profile, parser/OCR profile, raw storage mode, limits, partial indexing policy and ACL mode.
- default contracts live in `contracts/`; runtime copies live in `data/contracts/`.

### Graph Schema Bootstrapping

Graph schema bootstrapping is a moderated two-stage process focused on types, not concrete entity/fact instances.

Stage A: initiation.

- Process a curated initial document corpus by departments.
- Departments are chosen sequentially and should be process-diverse; the exact first departments are an implementation decision, not an architectural decision.
- The organization uses one unified graph schema in the first stage, not separate departmental schemas.
- Expensive local/cloud analysis is allowed only on a prepared, de-identified or pseudonymized package.
- Schema proposals must include evidence, examples, definitions, frequency, source coverage and negative examples where possible.
- Profile experts review schema deltas for their department.
- The graph owner gives final approval.
- Rejected schema proposals are stored as negative examples.
- Initiation is considered complete after the initial document corpus has been processed.

Stage B: working schema evolution.

- Run a permanent, cheaper statistical process over new or changed documents.
- Extract concrete graph entities and facts automatically using the accepted schema.
- Collect unknown patterns, conflicts, noisy terms and coverage gaps as schema proposals.
- Periodically route schema proposals to expert review and graph owner approval.

### Graph Instances

- Do not require a `GraphEntityCandidate` or `GraphFactCandidate` queue for every extracted instance.
- After schema acceptance, concrete `GraphEntity` and `GraphFact` records may be written automatically when they pass validation gates.
- Review queues are used only for exceptions: unknown type/relation, low confidence, conflict, suspicious canonicalization, DLP warning, partial document, or other policy risk.
- Every accepted graph fact must keep provenance: source, object id, snapshot hash, chunk id, evidence position, schema version, extractor, confidence, scope tokens and sensitivity.

## Alternatives Considered

### Use an external DMS/RAG product as the ingestion owner

Tools such as Paperless-ngx, Mayan EDMS, Cognee, GraphRAG products, NiFi or Airbyte could handle parts of ingestion or document processing.

Rejected as the authoritative ingestion owner because this project needs a single policy/audit/provenance model inside Django memory. External systems may still be used as parsers, references or adapters, but they must not bypass memory contracts, privacy gates or `memory.search`.

### Direct SMB client from day one

A Python SMB client could read shares directly.

Deferred because the first deployment is Windows Server and can access local/UNC paths through the service account. Direct SMB clients add credential handling, retry semantics and ACL complexity. The adapter interface must allow this later.

### Copy all raw documents into `data/memory/raw_vault/`

Rejected as the default because it increases storage, privacy and retention risk. It also creates a second raw document repository. Raw copies remain an explicit future mode for quarantine or reproducibility.

### Mandatory review queue for every entity and fact

Rejected because it does not match the intended operational model. Once the graph schema is accepted, routine entity/fact extraction should be automatic. Human review is reserved for schema evolution and high-risk extraction exceptions.

### Fully automatic graph schema discovery

Rejected because uncontrolled schema growth would create noisy types, duplicate concepts and weak graph semantics. Schema discovery must be moderated by profile experts and finalized by the graph owner.

## Consequences

### Positive

- The ingestion connector follows the existing local-first and contract-driven architecture.
- Windows/AD deployment is supported without storing SMB credentials in Django.
- The graph schema evolves through a controlled expert process.
- Concrete graph facts can be populated automatically without forcing experts to review every instance.
- PII/secret exposure is reduced by using safe/pseudonymized bootstrap packages for cloud tests.
- Partial indexing makes large documents usable while keeping review visibility.

### Negative

- More implementation work is required than adopting a single external ingestion platform.
- Parser/OCR quality must be tested against real Russian/English corporate documents.
- Schema bootstrapping requires expert availability.
- The project must implement review queues, schema versioning, extraction metrics and conflict handling.
- Cloud GLM-OCR tests need explicit preparation and policy controls before any real internal document is sent out.

### Required Follow-up

- Use `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md` as the implementation plan for ingestion connector and graph schema bootstrapping.
- Add `memory_graph_schema.json` and its JSON Schema.
- Decide whether ingestion profiles live in `memory_sources.json` or in a separate `memory_ingestion_profiles.json` contract.
- Add discovery state models, ingestion issue queue and graph schema proposal models.
- Add Windows deployment guidance for UNC paths, service accounts and gMSA.
- Add smoke/security tests for PII/secret leakage, parser failures, partial indexing and graph schema proposal workflows.
