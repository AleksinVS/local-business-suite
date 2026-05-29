import fnmatch
import hashlib
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.source_adapters import resolve_privacy_profile

from .acl import acl_blocks_ingestion, resolve_file_acl, scope_tokens_for_source_object
from .models import (
    MemoryGraphEntity,
    MemoryGraphExtractionRun,
    MemoryGraphReviewItem,
    MemoryGraphSchemaProposal,
    MemoryIngestionIssue,
    MemoryIngestionRun,
    MemorySearchDocument,
    MemorySource,
    MemorySourceObject,
)
from .security import scan_for_secrets
from .deidentification import detect_pii
from .source_text_extraction import (
    SUPPORTED_SOURCE_TEXT_EXTENSIONS,
    TextExtractionError,
    extract_text_from_file,
    extraction_limits_from_settings,
)
from .vector_backends import (
    LANCEDB_VECTOR_SCHEMA_VERSION,
    SQLITE_FTS_SCHEMA_VERSION,
    MemoryIndexRecord,
    get_default_backend,
    get_default_vector_backend,
)


ENCRYPTED_PDF_MARKER = b"/Encrypt"


@dataclass(frozen=True)
class IngestionProfile:
    profile_id: str
    adapter_kind: str
    supported_extensions: set[str]
    max_file_size_bytes: int
    raw_mode: str
    acl_mode: str
    unresolved_acl_policy: str
    acl_fail_closed: bool
    partial_indexing_enabled: bool
    follow_symlinks: bool
    stable_after_seconds: int


def discover_source_objects(*, source: MemorySource, dry_run=False, created_by=None):
    profile = get_source_ingestion_profile(source)
    run = _create_run(source=source, dry_run=dry_run, created_by=created_by)
    metrics = {
        "seen": 0,
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "missing": 0,
        "issues": 0,
        "dry_run": dry_run,
    }
    now = timezone.now()

    try:
        root = resolve_source_root(source)
        if not root.exists() or not root.is_dir():
            if not dry_run:
                _create_issue(
                    source=source,
                    run=run,
                    issue_kind=MemoryIngestionIssue.IssueKind.UNSUPPORTED_FORMAT,
                    severity=MemoryIngestionIssue.Severity.ERROR,
                    message=f"Source path does not exist or is not a directory: {source.source_ref if hasattr(source, 'source_ref') else source.config.get('source_ref')}",
                )
            metrics["issues"] += 1
            return _finish_run(run, metrics=metrics, status=MemoryIngestionRun.Status.FAILED, error_message="Source path is unavailable.")

        seen_object_ids = set()
        for file_path in iter_source_files(root=root, source=source, follow_symlinks=profile.follow_symlinks):
            stat = file_path.stat()
            relative_path = file_path.relative_to(root).as_posix()
            object_id = stable_object_id(source=source, relative_path=relative_path)
            seen_object_ids.add(object_id)
            metrics["seen"] += 1
            payload = build_source_object_payload(
                source=source,
                root=root,
                file_path=file_path,
                object_id=object_id,
                relative_path=relative_path,
                stat=stat,
                now=now,
                profile=profile,
            )
            existing = MemorySourceObject.objects.filter(source=source, object_id=object_id).first()
            if existing is None:
                metrics["new"] += 1
            elif existing.content_hash != payload["content_hash"] or existing.size_bytes != payload["size_bytes"]:
                metrics["changed"] += 1
            else:
                metrics["unchanged"] += 1

            if not dry_run:
                MemorySourceObject.objects.update_or_create(
                    source=source,
                    object_id=object_id,
                    defaults=payload,
                )

        missing_qs = MemorySourceObject.objects.filter(source=source).exclude(object_id__in=seen_object_ids)
        metrics["missing"] = missing_qs.count()
        if not dry_run:
            missing_qs.update(
                discovery_status=MemorySourceObject.DiscoveryStatus.MISSING,
                ingestion_status=MemorySourceObject.IngestionStatus.SKIPPED,
                updated_at=now,
            )
        return _finish_run(run, metrics=metrics)
    except Exception as exc:
        if not dry_run:
            _create_issue(
                source=source,
                run=run,
                issue_kind=MemoryIngestionIssue.IssueKind.UNSUPPORTED_FORMAT,
                severity=MemoryIngestionIssue.Severity.ERROR,
                message=str(exc),
            )
        metrics["issues"] += 1
        return _finish_run(run, metrics=metrics, status=MemoryIngestionRun.Status.FAILED, error_message=str(exc))


def ingest_source_objects(*, source: MemorySource, dry_run=False, created_by=None, limit=None):
    profile = get_source_ingestion_profile(source)
    if not dry_run and not MemorySourceObject.objects.filter(source=source).exists():
        discover_source_objects(source=source, dry_run=False, created_by=created_by)

    run = _create_run(source=source, dry_run=dry_run, created_by=created_by)
    metrics = {
        "eligible": 0,
        "ingested": 0,
        "skipped": 0,
        "partial": 0,
        "issues": 0,
        "dry_run": dry_run,
    }
    queryset = MemorySourceObject.objects.filter(
        source=source,
        discovery_status__in=[MemorySourceObject.DiscoveryStatus.SEEN, MemorySourceObject.DiscoveryStatus.CHANGED],
    ).order_by("relative_path")
    if limit:
        queryset = queryset[:limit]

    try:
        for source_object in queryset:
            metrics["eligible"] += 1
            outcome = inspect_source_object_for_ingestion(source_object=source_object, profile=profile)
            if dry_run:
                metrics[outcome["metric"]] += 1
                continue
            if outcome["issue_kind"]:
                _create_issue(
                    source=source,
                    source_object=source_object,
                    run=run,
                    issue_kind=outcome["issue_kind"],
                    severity=outcome["severity"],
                    message=outcome["message"],
                    metadata=outcome["metadata"],
                )
                metrics["issues"] += 1
            if outcome["status"] in {
                MemorySourceObject.IngestionStatus.SKIPPED,
                MemorySourceObject.IngestionStatus.FAILED,
            }:
                _mark_source_object(source_object, status=outcome["status"], error=outcome["message"])
                metrics["skipped"] += 1
                continue

            try:
                document_result = ingest_source_object_text(
                    source_object=source_object,
                    safe_text=outcome["text"],
                    partial_reason=outcome["partial_reason"],
                    extraction_metadata=outcome["metadata"].get("extraction"),
                )
            except ValueError as exc:
                _create_issue(
                    source=source,
                    source_object=source_object,
                    run=run,
                    issue_kind=MemoryIngestionIssue.IssueKind.SECRET_BLOCKED,
                    severity=MemoryIngestionIssue.Severity.BLOCKER,
                    message=str(exc),
                    metadata=outcome["metadata"],
                )
                _mark_source_object(source_object, status=MemorySourceObject.IngestionStatus.FAILED, error=str(exc))
                metrics["issues"] += 1
                metrics["skipped"] += 1
                continue
            _mark_source_object(
                source_object,
                status=outcome["status"],
                partial_reason=outcome["partial_reason"],
                ingested=True,
                metadata={"document_id": document_result["document_id"], **outcome["metadata"]},
            )
            metrics["partial" if outcome["status"] == MemorySourceObject.IngestionStatus.PARTIAL else "ingested"] += 1
        return _finish_run(run, metrics=metrics)
    except Exception as exc:
        return _finish_run(run, metrics=metrics, status=MemoryIngestionRun.Status.FAILED, error_message=str(exc))


def prepare_bootstrap_package(*, source: MemorySource, department: str, dry_run=False, limit=None):
    objects = MemorySourceObject.objects.filter(
        source=source,
        ingestion_status__in=[MemorySourceObject.IngestionStatus.INGESTED, MemorySourceObject.IngestionStatus.PARTIAL],
    ).order_by("relative_path")
    if limit:
        objects = objects[:limit]
    blocks = []
    for source_object in objects:
        document = MemorySearchDocument.objects.filter(
            source_object=source_object,
            corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA,
            index_status=MemorySearchDocument.IndexStatus.READY,
        ).first()
        if document is None:
            continue
        try:
            text = _read_text_file(Path(source_object.object_uri))
        except OSError:
            text = ""
        blocks.append(
            {
                "source_code": source.code,
                "department": department,
                "object_id": source_object.object_id,
                "relative_path": source_object.relative_path,
                "document_id": document.document_id,
                "text_hash": document.body_hash,
                "text": text,
            }
        )
    package = {
        "source_code": source.code,
        "department": department,
        "created_at": timezone.now().isoformat(),
        "block_count": len(blocks),
        "blocks": blocks,
        "approval_required_before_cloud": True,
    }
    if dry_run:
        return package
    path = settings.DATA_DIR / "memory" / "bootstrap_packages" / f"{source.code}_{_safe_name(department)}.json"
    from apps.core.json_utils import atomic_write_json

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, package)
    return {**package, "path": str(path)}


def discover_schema_proposals_from_package(*, package, dry_run=False):
    proposals = []
    seen_terms = {}
    for block in package.get("blocks", []):
        text = block.get("text", "")
        for marker, proposal_kind, entity_type in (
            ("отдел", MemoryGraphSchemaProposal.ProposalKind.ENTITY_TYPE, "Department"),
            ("процедур", MemoryGraphSchemaProposal.ProposalKind.ENTITY_TYPE, "Procedure"),
            ("инструкц", MemoryGraphSchemaProposal.ProposalKind.ENTITY_TYPE, "Document"),
        ):
            if marker.lower() in text.lower():
                key = (proposal_kind, entity_type)
                seen_terms.setdefault(key, []).append(
                    {
                        "source_code": block.get("source_code"),
                        "object_id": block.get("object_id"),
                        "document_id": block.get("document_id"),
                        "text_hash": block.get("text_hash"),
                    }
                )
    for (proposal_kind, entity_type), evidence in seen_terms.items():
        payload = {
            "code": entity_type,
            "status": "proposed",
            "source": "local-statistical-bootstrap-v1",
        }
        proposals.append({"proposal_kind": proposal_kind, "payload": payload, "evidence": evidence, "confidence": "0.6000"})
        if not dry_run:
            MemoryGraphSchemaProposal.objects.create(
                proposal_kind=proposal_kind,
                status=MemoryGraphSchemaProposal.Status.NEEDS_EXPERT_REVIEW,
                department=package.get("department", ""),
                payload=payload,
                evidence=evidence,
                confidence="0.6000",
                rationale="Local bootstrap proposal from repeated marker terms.",
            )
    return {"proposal_count": len(proposals), "proposals": proposals}


def extract_graph_instances(*, source: MemorySource, dry_run=False, limit=None):
    run = MemoryGraphExtractionRun.objects.create(
        source=source,
        status=MemoryGraphExtractionRun.Status.RUNNING,
        started_at=timezone.now(),
    )
    metrics = {"documents": 0, "entities": 0, "facts": 0, "review_items": 0, "dry_run": dry_run}
    documents = MemorySearchDocument.objects.select_related("source_object", "source_object__source").filter(
        source_object__source=source,
        corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA,
        index_status=MemorySearchDocument.IndexStatus.READY,
    )
    try:
        for document in documents.order_by("document_id"):
            if limit and metrics["documents"] >= limit:
                break
            metrics["documents"] += 1
            try:
                text = _read_text_file(Path(document.source_object.object_uri))
            except OSError:
                text = ""
            entity_payloads = _extract_simple_entities(text)
            if dry_run:
                metrics["entities"] += len(entity_payloads)
                continue
            for payload in entity_payloads:
                MemoryGraphEntity.objects.update_or_create(
                    entity_id=payload["entity_id"],
                    defaults={
                        "entity_type": payload["entity_type"],
                        "canonical_name": payload["canonical_name"],
                        "aliases": [],
                        "attributes": payload.get("attributes", {}),
                        "scope_tokens": (document.source_object.metadata or {}).get("scope_tokens") or [],
                        "sensitivity": document.source_object.source.sensitivity,
                        "is_active": True,
                    },
                )
                metrics["entities"] += 1
            if "unknown:" in text:
                MemoryGraphReviewItem.objects.create(
                    item_kind=MemoryGraphReviewItem.ItemKind.UNKNOWN_TYPE,
                    status=MemoryGraphReviewItem.Status.NEEDS_EXPERT_REVIEW,
                    source=source,
                    payload={"marker": "unknown:"},
                    evidence=[{"document_id": document.document_id}],
                )
                metrics["review_items"] += 1
        run.status = MemoryGraphExtractionRun.Status.SUCCEEDED
        run.finished_at = timezone.now()
        run.metrics = metrics
        run.save(update_fields=["status", "finished_at", "metrics", "updated_at"])
        return metrics
    except Exception as exc:
        run.status = MemoryGraphExtractionRun.Status.FAILED
        run.finished_at = timezone.now()
        run.error_message = str(exc)
        run.metrics = metrics
        run.save(update_fields=["status", "finished_at", "error_message", "metrics", "updated_at"])
        raise


def get_source_ingestion_profile(source: MemorySource):
    payload = getattr(settings, "LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES", {}) or {}
    profile_id = source.config.get("ingestion_profile") or source.config.get("ingestion", {}).get("profile") or "corporate_docs_windows_v1"
    profile = payload.get("profiles", {}).get(profile_id)
    if not profile:
        raise ValueError(f"Unknown memory ingestion profile '{profile_id}'.")
    adapter = payload["adapter_profiles"][profile["adapter_profile"]]
    parser = payload["parser_profiles"][profile["parser_profile"]]
    limit_profile = payload["limit_profiles"][profile["limit_profile"]]
    return IngestionProfile(
        profile_id=profile_id,
        adapter_kind=adapter["adapter_kind"],
        supported_extensions={ext.lower() for ext in parser.get("supported_extensions", [])} | SUPPORTED_SOURCE_TEXT_EXTENSIONS,
        max_file_size_bytes=int(limit_profile["max_file_size_mb"]) * 1024 * 1024,
        raw_mode=profile["raw_mode"],
        acl_mode=profile["acl_mode"],
        unresolved_acl_policy=profile.get("acl_policy", {}).get(
            "unresolved_policy",
            getattr(settings, "MEMORY_ACL_UNRESOLVED_POLICY", "block"),
        ),
        acl_fail_closed=bool(
            profile.get("acl_policy", {}).get(
                "fail_closed",
                getattr(settings, "MEMORY_ACL_FAIL_CLOSED", True),
            )
        ),
        partial_indexing_enabled=profile["partial_indexing"] == "enabled",
        follow_symlinks=bool(adapter.get("follow_symlinks", False)),
        stable_after_seconds=int(adapter.get("stable_after_seconds", 5)),
    )


def resolve_source_root(source: MemorySource):
    source_ref = source.config.get("source_ref") or source.config.get("path") or source.code
    if source_ref.startswith("synthetic:"):
        raise ValueError("Synthetic sources are not file ingestion sources.")
    return Path(source_ref)


def iter_source_files(*, root: Path, source: MemorySource, follow_symlinks=False):
    ignore_patterns = source.config.get("ignore_patterns") or []
    for path in root.rglob("*"):
        if path.is_symlink() and not follow_symlinks:
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(relative, pattern) for pattern in ignore_patterns):
            continue
        yield path


def build_source_object_payload(*, source, root, file_path, object_id, relative_path, stat, now, profile):
    content_hash = sha256_file(file_path)
    mime_type, _ = mimetypes.guess_type(str(file_path))
    extension = file_path.suffix.lower()
    acl_resolution = None
    if profile.acl_mode in {"inherit_source_acl", "inherit_source_acl_with_fallback"}:
        acl_resolution = resolve_file_acl(
            source=source,
            root=root,
            file_path=file_path,
            relative_path=relative_path,
        )
    return {
        "object_uri": str(file_path),
        "relative_path": relative_path,
        "file_name": file_path.name,
        "extension": extension,
        "mime_type": mime_type or "application/octet-stream",
        "size_bytes": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
        "content_hash": content_hash,
        "etag_or_inode": str(getattr(stat, "st_ino", "")),
        "last_seen_at": now,
        "last_stable_at": now if now.timestamp() - stat.st_mtime >= profile.stable_after_seconds else None,
        "discovery_status": MemorySourceObject.DiscoveryStatus.SEEN,
        "ingestion_status": MemorySourceObject.IngestionStatus.PENDING,
        "last_error": "",
        "partial_reason": "",
        "acl_fingerprint": acl_resolution.fingerprint if acl_resolution else "",
        "metadata": {
            "raw_mode": profile.raw_mode,
            "acl_mode": profile.acl_mode,
            **({"acl": acl_resolution.as_metadata()} if acl_resolution else {}),
        },
    }


def inspect_source_object_for_ingestion(*, source_object: MemorySourceObject, profile: IngestionProfile):
    path = Path(source_object.object_uri)
    extension = source_object.extension.lower()
    base = {
        "text": "",
        "partial_reason": "",
        "issue_kind": "",
        "severity": MemoryIngestionIssue.Severity.WARNING,
        "message": "",
        "metadata": {"relative_path": source_object.relative_path},
        "metric": "ingested",
        "status": MemorySourceObject.IngestionStatus.INGESTED,
    }
    if extension not in profile.supported_extensions:
        return {
            **base,
            "issue_kind": MemoryIngestionIssue.IssueKind.UNSUPPORTED_FORMAT,
            "message": f"Unsupported extension: {extension or '<none>'}",
            "metric": "skipped",
            "status": MemorySourceObject.IngestionStatus.SKIPPED,
        }
    blocked_by_acl, acl_reason, acl_metadata = acl_blocks_ingestion(
        source_object=source_object,
        profile=profile,
    )
    if blocked_by_acl:
        return {
            **base,
            "issue_kind": MemoryIngestionIssue.IssueKind.ACL_UNRESOLVED,
            "severity": MemoryIngestionIssue.Severity.BLOCKER,
            "message": acl_reason,
            "metric": "skipped",
            "status": MemorySourceObject.IngestionStatus.SKIPPED,
            "metadata": {**base["metadata"], "acl": acl_metadata},
        }
    forced_partial_reason = ""
    if source_object.size_bytes > profile.max_file_size_bytes:
        if not profile.partial_indexing_enabled or extension not in SUPPORTED_SOURCE_TEXT_EXTENSIONS:
            return {
                **base,
                "issue_kind": MemoryIngestionIssue.IssueKind.FILE_TOO_LARGE,
                "message": f"File exceeds {profile.max_file_size_bytes} bytes.",
                "metric": "skipped",
                "status": MemorySourceObject.IngestionStatus.SKIPPED,
            }
        forced_partial_reason = f"File exceeds {profile.max_file_size_bytes} bytes; indexed supported extracted text within limits."
    if extension == ".pdf" and _file_contains(path, ENCRYPTED_PDF_MARKER):
        return {
            **base,
            "issue_kind": MemoryIngestionIssue.IssueKind.ENCRYPTED_FILE,
            "severity": MemoryIngestionIssue.Severity.ERROR,
            "message": "Encrypted PDF was skipped.",
            "metric": "skipped",
            "status": MemorySourceObject.IngestionStatus.SKIPPED,
        }
    if extension in SUPPORTED_SOURCE_TEXT_EXTENSIONS:
        try:
            extracted = extract_text_from_file(path, limits=extraction_limits_from_settings())
        except TextExtractionError as exc:
            issue_kind = getattr(MemoryIngestionIssue.IssueKind, str(exc.issue_kind).upper(), MemoryIngestionIssue.IssueKind.UNSUPPORTED_FORMAT)
            return {
                **base,
                "issue_kind": issue_kind,
                "severity": MemoryIngestionIssue.Severity.ERROR,
                "message": str(exc),
                "metric": "skipped",
                "status": MemorySourceObject.IngestionStatus.SKIPPED,
                "metadata": {**base["metadata"], **(exc.metadata or {})},
            }
        secret_scan = scan_for_secrets(extracted.text)
        if secret_scan.blocked:
            return {
                **base,
                "issue_kind": MemoryIngestionIssue.IssueKind.SECRET_BLOCKED,
                "severity": MemoryIngestionIssue.Severity.BLOCKER,
                "message": secret_scan.reason or "Sensitive credential material was detected.",
                "metric": "skipped",
                "status": MemorySourceObject.IngestionStatus.FAILED,
                "metadata": {
                    **base["metadata"],
                    "secret_findings": _safe_secret_findings(secret_scan.findings),
                },
            }
        partial_reason = forced_partial_reason or extracted.partial_reason
        privacy_profile = _privacy_profile_for_source(source_object.source)
        pii_findings = detect_pii(extracted.text, secret_key=settings.SECRET_KEY) if privacy_profile.detect else ()
        metadata = {
            **base["metadata"],
            "extraction": extracted.metadata,
            **({"pii_findings": [finding.as_dict() for finding in pii_findings]} if pii_findings else {}),
        }
        pii_issue = {
            "issue_kind": MemoryIngestionIssue.IssueKind.PII_AUDIT,
            "severity": MemoryIngestionIssue.Severity.WARNING,
            "message": "PII-like data was detected; document will be indexed and queued for audit.",
        } if pii_findings and privacy_profile.audit else {}
        if extracted.partial or forced_partial_reason:
            return {
                **base,
                "text": extracted.text,
                "partial_reason": partial_reason,
                "issue_kind": pii_issue.get("issue_kind") or MemoryIngestionIssue.IssueKind.PARTIAL_INDEXED,
                "severity": pii_issue.get("severity", MemoryIngestionIssue.Severity.WARNING),
                "message": pii_issue.get("message") or "Document was partially indexed within extraction limits.",
                "metric": "partial",
                "status": MemorySourceObject.IngestionStatus.PARTIAL,
                "metadata": metadata,
            }
        return {**base, **pii_issue, "text": extracted.text, "metadata": metadata}
    return {
        **base,
        "issue_kind": MemoryIngestionIssue.IssueKind.UNSUPPORTED_FORMAT,
        "message": f"Парсер или OCR для {extension} не включен в текущем MVP.",
        "metric": "skipped",
        "status": MemorySourceObject.IngestionStatus.SKIPPED,
        "metadata": {**base["metadata"], "requires_external_parser_or_ocr": True},
    }


@transaction.atomic
def ingest_source_object_text(
    *,
    source_object: MemorySourceObject,
    safe_text: str,
    partial_reason="",
    extraction_metadata=None,
    index_backends=("fulltext", "vector"),
):
    source = source_object.source
    profile = get_source_ingestion_profile(source)
    scope_tokens = scope_tokens_for_source_object(source_object=source_object, profile=profile)
    if not scope_tokens:
        raise ValueError("No resolved memory scope tokens for source object.")
    index_body = safe_text or ""
    secret_scan = scan_for_secrets(index_body)
    if secret_scan.blocked:
        raise ValueError(secret_scan.reason or "Source object was blocked by secret scanning.")
    privacy_profile = _privacy_profile_for_source(source)
    pii_findings = detect_pii(index_body, secret_key=settings.SECRET_KEY) if privacy_profile.detect else ()
    document_id = _source_document_id(source_object)
    selected_backends = set(index_backends or ())
    fulltext_backend = get_default_backend() if "fulltext" in selected_backends else None
    vector_backend = get_default_vector_backend() if "vector" in selected_backends else None
    existing_document = MemorySearchDocument.objects.filter(document_id=document_id).first()
    existing_versions = dict(((existing_document.metadata or {}).get("index_versions") if existing_document else {}) or {})
    if "fulltext" in selected_backends:
        existing_versions["fulltext"] = SQLITE_FTS_SCHEMA_VERSION
    if vector_backend is not None:
        existing_versions["vector"] = LANCEDB_VECTOR_SCHEMA_VERSION
        embedding_metadata = vector_backend.embedding_provider.metadata
    else:
        embedding_metadata = None
    metadata = {
        "relative_path": source_object.relative_path,
        "file_name": source_object.file_name,
        "partial": bool(partial_reason),
        "partial_reason": partial_reason,
        "raw_mode": "reference_only",
        "acl": (source_object.metadata or {}).get("acl", {}),
        "source_object_id": source_object.object_id,
        "content_hash": source_object.content_hash,
        "acl_fingerprint": source_object.acl_fingerprint,
        "sensitivity": source.sensitivity,
        "trust_status": source.trust_status,
        "authority_class": source.authority_class,
        "extraction": dict(extraction_metadata or {}),
        "index_versions": existing_versions,
        "embedding": embedding_metadata.__dict__ if embedding_metadata is not None else {},
        "pii_detected": bool(pii_findings),
        "pii_finding_count": len(pii_findings),
    }
    document, _ = MemorySearchDocument.objects.update_or_create(
        document_id=document_id,
        defaults={
            "corpus_type": MemorySearchDocument.CorpusType.SOURCE_DATA,
            "object_kind": MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
            "source_object": source_object,
            "body_hash": sha256_text(index_body),
            "index_status": MemorySearchDocument.IndexStatus.READY,
            "metadata": metadata,
            "indexed_at": timezone.now(),
        },
    )
    source_object.metadata = {
        **(source_object.metadata or {}),
        "scope_tokens": scope_tokens,
        "last_search_document_id": document.document_id,
        "last_extraction": dict(extraction_metadata or {}),
    }
    source_object.save(update_fields=["metadata", "updated_at"])
    index_text = "\n".join(
        value
        for value in [
            source_object.file_name,
            source_object.relative_path,
            source_object.object_id,
            source_object.content_hash,
            index_body,
        ]
        if value
    )
    record = MemoryIndexRecord(
        document_id=document.document_id,
        text=index_text,
        metadata={
            **metadata,
            "corpus_type": "source_data",
            "result_type": "source_data",
            "source_code": source.code,
            "source_kind": source.source_kind,
            "source_object_id": source_object.object_id,
            "content_hash": source_object.content_hash,
        },
        scope_tokens=scope_tokens,
        sensitivity=source.sensitivity,
        is_active=True,
    )
    if fulltext_backend is not None:
        fulltext_backend.upsert(record)
    if vector_backend is not None:
        vector_backend.upsert(record)
    return {"document_id": document.document_id, "document_ids": [document.document_id], "source_object_id": source_object.object_id}


def delete_search_document_indexes(document_ids, *, index_backends=("fulltext", "vector")) -> dict:
    selected_backends = set(index_backends or ())
    ids = [str(document_id or "").strip() for document_id in document_ids if str(document_id or "").strip()]
    result = {"fulltext_deleted": 0, "vector_deleted": 0}
    if not ids:
        return result
    if "fulltext" in selected_backends:
        result["fulltext_deleted"] = get_default_backend().delete(ids)
    if "vector" in selected_backends:
        vector_backend = get_default_vector_backend()
        if vector_backend is not None:
            result["vector_deleted"] = vector_backend.delete(ids)
    return result


def stable_object_id(*, source: MemorySource, relative_path: str):
    return "file:" + hashlib.sha256(f"{source.code}:{relative_path}".encode("utf-8")).hexdigest()[:40]


def _source_document_id(source_object: MemorySourceObject):
    return "source:" + hashlib.sha256(f"{source_object.source.code}:{source_object.object_id}".encode("utf-8")).hexdigest()[:40]


def sha256_text(value: str):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _privacy_profile_for_source(source: MemorySource):
    return resolve_privacy_profile(
        explicit_profile=(source.config or {}).get("privacy_profile", ""),
        pii_policy=source.pii_policy,
        source_origin=(source.config or {}).get("source_origin", ""),
        source_kind=source.source_kind,
    )


def _safe_secret_findings(findings):
    safe = []
    for finding in findings:
        safe.append(
            {
                "type": finding.finding_type,
                "start": finding.start,
                "end": finding.end,
                "reason": finding.reason,
                "confidence": finding.confidence,
            }
        )
    return safe


def sha256_file(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text_file(path: Path, max_bytes=None):
    data = path.read_bytes() if max_bytes is None else path.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="replace")


def _file_contains(path: Path, marker: bytes):
    try:
        return marker in path.read_bytes()[:1024 * 1024]
    except OSError:
        return False


def _create_run(*, source, dry_run=False, created_by=None):
    if dry_run:
        return None
    return MemoryIngestionRun.objects.create(
        source=source,
        status=MemoryIngestionRun.Status.RUNNING,
        started_at=timezone.now(),
        dry_run=False,
        created_by=created_by,
    )


def _finish_run(run, *, metrics, status=MemoryIngestionRun.Status.SUCCEEDED, error_message=""):
    if run is not None:
        run.status = status
        run.finished_at = timezone.now()
        run.metrics = metrics
        run.error_message = error_message
        run.save(update_fields=["status", "finished_at", "metrics", "error_message", "updated_at"])
    return metrics


def _create_issue(*, source, issue_kind, message, severity, run=None, source_object=None, metadata=None):
    return MemoryIngestionIssue.objects.create(
        source=source,
        source_object=source_object,
        run=run,
        issue_kind=issue_kind,
        severity=severity,
        message=message,
        metadata=metadata or {},
    )


def _mark_source_object(source_object, *, status, error="", partial_reason="", ingested=False, metadata=None):
    source_object.ingestion_status = status
    source_object.last_error = error
    source_object.partial_reason = partial_reason
    if ingested:
        source_object.last_ingested_at = timezone.now()
    if error:
        source_object.failure_count += 1
    if metadata:
        source_object.metadata = {**(source_object.metadata or {}), **metadata}
    source_object.save(
        update_fields=[
            "ingestion_status",
            "last_error",
            "partial_reason",
            "last_ingested_at",
            "failure_count",
            "metadata",
            "updated_at",
        ]
    )


def _extract_simple_entities(text: str):
    entities = []
    for marker, entity_type in (("Отдел ", "Department"), ("Инструкция ", "Document"), ("Процедура ", "Procedure")):
        if marker.lower() in text.lower():
            canonical_name = marker.strip()
            entities.append(
                {
                    "entity_id": "entity:" + hashlib.sha256(f"{entity_type}:{canonical_name}".encode("utf-8")).hexdigest()[:32],
                    "entity_type": entity_type,
                    "canonical_name": canonical_name,
                    "attributes": {"source": "local-pattern-extractor-v1"},
                }
            )
    return entities


def _safe_name(value: str):
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("._") or "department"
