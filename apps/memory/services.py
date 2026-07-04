import hashlib
from collections.abc import Iterable

from django.conf import settings
from django.utils import timezone

from apps.core.source_adapters import (
    ACCESS_MODE_ADAPTER_CHECK,
    OPERATION_DELETE,
    SourceObjectEnvelope,
    get_source_adapter,
    resolve_privacy_profile,
)

from .knowledge_files import read_knowledge_item_file
from .deidentification import detect_pii, redact_text
from .document_ingestion import delete_search_document_indexes
from .models import (
    MemoryAccessAudit,
    MemoryExternalConnectorJob,
    MemoryIngestionIssue,
    MemoryKnowledgeItem,
    MemorySearchDocument,
    MemorySource,
    MemorySourceObject,
)
from .policies import user_scope_tokens
from .security import scan_for_secrets
from .vector_backends import (
    LANCEDB_VECTOR_SCHEMA_VERSION,
    MemoryIndexRecord,
    get_default_backend,
    get_default_fulltext_schema_version,
    get_default_vector_backend,
)


def sync_sources_from_contract(sources_payload):
    sources = []
    for item in sources_payload:
        source, _ = MemorySource.objects.update_or_create(
            code=item["code"],
            defaults={
                "title": item["title"],
                "source_kind": item["source_kind"],
                "domain": item["domain"],
                "owner": item.get("owner", ""),
                "status": MemorySource.Status.ENABLED if item.get("enabled", True) else MemorySource.Status.DISABLED,
                "trust_status": item.get("trust_status", ""),
                "authority_class": item.get("authority_class", ""),
                "trusted_for_context": bool(item.get("trusted_for_context", False)),
                "requires_source_review": bool(item.get("requires_source_review", True)),
                "review_owner": item.get("review_owner", ""),
                "trusted_context_kinds": item.get("trusted_context_kinds", []),
                "untrusted_handling": item.get("untrusted_handling", ""),
                "sync_mode": item.get("sync_mode", ""),
                "scope_rule": item.get("scope_rule", ""),
                "sensitivity": item["sensitivity"],
                "pii_policy": item.get("pii_policy", ""),
                "extractor_profile": item.get("extractor_profile", ""),
                "chunking_profile": item.get("chunking_profile", ""),
                "index_profiles": item.get("index_profiles", []),
                "config": item,
            },
        )
        sources.append(source)
    return sources


def upsert_memory_projection_from_envelope(
    envelope: SourceObjectEnvelope,
    *,
    index_backends: Iterable[str] = ("fulltext", "vector"),
    dry_run: bool = False,
):
    """Create or refresh memory source-data projection from a normalized source envelope."""
    if envelope.operation == OPERATION_DELETE:
        return delete_memory_projection_from_envelope(envelope, index_backends=index_backends, dry_run=dry_run)

    if dry_run:
        privacy_profile = resolve_privacy_profile(
            explicit_profile=envelope.privacy_profile,
            source_origin=envelope.source_origin,
            source_kind=envelope.source_kind,
        )
        secret_scan = scan_for_secrets(envelope.text or "")
        pii_findings = detect_pii(envelope.text or "", secret_key=settings.SECRET_KEY) if privacy_profile.detect and not secret_scan.blocked else ()
        return {
            "source_code": envelope.source_code,
            "source_object_id": envelope.object_id,
            "document_id": source_adapter_document_id(source_code=envelope.source_code, object_id=envelope.object_id),
            "blocked": bool(secret_scan.blocked or (pii_findings and privacy_profile.block)),
            "issues": [
                *(
                    [
                        {
                            "issue_kind": MemoryIngestionIssue.IssueKind.SECRET_BLOCKED,
                            "severity": MemoryIngestionIssue.Severity.BLOCKER,
                            "message": secret_scan.reason,
                        }
                    ]
                    if secret_scan.blocked
                    else []
                ),
                *(
                    [
                        {
                            "issue_kind": MemoryIngestionIssue.IssueKind.PII_AUDIT,
                            "severity": MemoryIngestionIssue.Severity.WARNING,
                            "message": "Похожий на персональные данные контент будет отправлен на аудит.",
                        }
                    ]
                    if pii_findings and privacy_profile.audit
                    else []
                ),
            ],
            "dry_run": True,
        }

    source = _ensure_memory_source_from_envelope(envelope)
    source_object = _ensure_memory_source_object_from_envelope(source=source, envelope=envelope)
    privacy_profile = resolve_privacy_profile(
        explicit_profile=envelope.privacy_profile,
        source_origin=envelope.source_origin,
        source_kind=envelope.source_kind,
    )
    gate = _prepare_source_text_for_index(
        envelope=envelope,
        source=source,
        source_object=source_object,
        privacy_profile=privacy_profile,
        dry_run=dry_run,
    )
    if gate["blocked"]:
        if not dry_run:
            source_object.ingestion_status = MemorySourceObject.IngestionStatus.FAILED
            source_object.last_error = gate["message"]
            source_object.save(update_fields=["ingestion_status", "last_error", "updated_at"])
        return {
            "source_code": source.code,
            "source_object_id": source_object.object_id,
            "document_id": "",
            "blocked": True,
            "issues": gate["issues"],
            "dry_run": dry_run,
        }

    document_id = source_adapter_document_id(source_code=envelope.source_code, object_id=envelope.object_id)
    document_metadata = _memory_document_metadata(
        envelope=envelope,
        source=source,
        source_object=source_object,
        safe_text=gate["safe_text"],
        pii_findings=gate["pii_findings"],
    )
    if dry_run:
        return {
            "source_code": source.code,
            "source_object_id": source_object.object_id,
            "document_id": document_id,
            "blocked": False,
            "issues": gate["issues"],
            "dry_run": True,
        }

    document, _created = MemorySearchDocument.objects.update_or_create(
        document_id=document_id,
        defaults={
            "corpus_type": MemorySearchDocument.CorpusType.SOURCE_DATA,
            "object_kind": MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
            "source_object": source_object,
            "body_hash": sha256_text(gate["safe_text"]),
            "index_status": MemorySearchDocument.IndexStatus.READY,
            "metadata": document_metadata,
            "indexed_at": timezone.now(),
        },
    )
    source_object.ingestion_status = MemorySourceObject.IngestionStatus.INGESTED
    source_object.last_ingested_at = timezone.now()
    source_object.last_error = ""
    source_object.metadata = {
        **(source_object.metadata or {}),
        "last_search_document_id": document.document_id,
        "safe_text": gate["safe_text"],
        "scope_tokens": _envelope_scope_tokens(envelope),
        "privacy_profile": privacy_profile.profile_id,
        "access_policy": dict(envelope.access_policy or {}),
        "provenance": dict(envelope.provenance or {}),
    }
    source_object.save(update_fields=["ingestion_status", "last_ingested_at", "last_error", "metadata", "updated_at"])

    _upsert_projection_indexes(
        document=document,
        envelope=envelope,
        safe_text=gate["safe_text"],
        metadata=document_metadata,
        index_backends=index_backends,
    )
    return {
        "source_code": source.code,
        "source_object_id": source_object.object_id,
        "document_id": document.document_id,
        "blocked": False,
        "issues": gate["issues"],
        "dry_run": False,
    }


def delete_memory_projection_from_envelope(
    envelope: SourceObjectEnvelope,
    *,
    index_backends: Iterable[str] = ("fulltext", "vector"),
    dry_run: bool = False,
):
    source = MemorySource.objects.filter(code=envelope.source_code).first()
    if source is None:
        return {"source_code": envelope.source_code, "deleted": 0, "dry_run": dry_run}
    source_object = MemorySourceObject.objects.filter(source=source, object_id=envelope.object_id).first()
    if source_object is None:
        return {"source_code": source.code, "deleted": 0, "dry_run": dry_run}
    documents = list(MemorySearchDocument.objects.filter(source_object=source_object).values_list("document_id", flat=True))
    if dry_run:
        return {"source_code": source.code, "deleted": len(documents), "dry_run": True}
    if documents:
        delete_search_document_indexes(documents, index_backends=index_backends)
        MemorySearchDocument.objects.filter(document_id__in=documents).update(
            index_status=MemorySearchDocument.IndexStatus.DELETED,
            indexed_at=timezone.now(),
        )
    source_object.discovery_status = MemorySourceObject.DiscoveryStatus.MISSING
    source_object.ingestion_status = MemorySourceObject.IngestionStatus.SKIPPED
    source_object.metadata = {**(source_object.metadata or {}), "deleted_by_source_adapter": True}
    source_object.save(update_fields=["discovery_status", "ingestion_status", "metadata", "updated_at"])
    return {"source_code": source.code, "deleted": len(documents), "dry_run": False}


def can_access_source_object_via_adapter(user, source_object: MemorySourceObject) -> bool:
    access_policy = (source_object.metadata or {}).get("access_policy") or {}
    if access_policy.get("mode") != ACCESS_MODE_ADAPTER_CHECK:
        return True
    adapter = get_source_adapter(source_object.source.code)
    if adapter is None:
        return False
    try:
        return bool(adapter.can_access(user, source_object.object_id))
    except Exception:
        return False


def render_source_object_text(source_object: MemorySourceObject, *, actor=None) -> str:
    access_policy = (source_object.metadata or {}).get("access_policy") or {}
    if access_policy.get("mode") == ACCESS_MODE_ADAPTER_CHECK:
        adapter = get_source_adapter(source_object.source.code)
        if adapter is None:
            return ""
        if actor is not None and not can_access_source_object_via_adapter(actor, source_object):
            return ""
        source_record = adapter.get_object(source_object.object_id)
        if source_record is not None:
            return adapter.render_envelope(source_record).text
    metadata = source_object.metadata or {}
    if metadata.get("safe_text"):
        return str(metadata.get("safe_text") or "")
    return source_object.file_name or source_object.relative_path or source_object.object_id


def source_adapter_document_id(*, source_code: str, object_id: str) -> str:
    return "source:" + hashlib.sha256(f"{source_code}:{object_id}".encode("utf-8")).hexdigest()[:40]


def compile_knowledge_item_digest(*, scope_tokens=None, limit=100):
    queryset = MemoryKnowledgeItem.objects.filter(status=MemoryKnowledgeItem.Status.ACTIVE).order_by("-updated_at", "-id")
    tokens = set(scope_tokens or [])
    records = []
    for item in queryset[: max(int(limit), 1)]:
        if tokens and not set(item.scope_tokens or []) & tokens:
            continue
        try:
            text = read_knowledge_item_file(item).body
        except Exception:
            text = ""
        records.append(
            {
                "memory_id": item.memory_id,
                "text": text,
                "scope": item.scope,
                "scope_tokens": item.scope_tokens,
                "sensitivity": item.sensitivity,
                "updated_at": item.updated_at.isoformat(),
            }
        )
    return records


class MemoryQueueJobKind:
    """Task kinds carried by the single unified memory queue.

    ADR-0030 decision 2: MemoryWriteRequest/MemoryIndexJob/MemoryKnowledgeEvent/
    MemoryReflectionRun collapse into ``MemoryExternalConnectorJob``. The queue
    already carries external-connector kinds (see ``external_connectors.ExternalJobKind``);
    these are the additional kinds used by the rest of the memory app.
    """

    RECONCILE = "reconcile"
    INGESTION = "ingestion"
    REINDEX = "reindex"


class MemoryQueueStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


def enqueue_memory_queue_task(
    *,
    job_kind: str,
    idempotency_key: str,
    payload: dict | None = None,
    source_code: str = "",
    priority: int = 0,
    max_attempts: int = 3,
    request_id: str = "",
) -> MemoryExternalConnectorJob:
    """Enqueue a task on the single unified memory queue table.

    Idempotent by ``idempotency_key``: a repeat enqueue with the same key
    returns the existing row instead of creating a duplicate.
    """
    job, _created = MemoryExternalConnectorJob.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "source_code": source_code,
            "job_kind": job_kind,
            "status": MemoryQueueStatus.PENDING,
            "priority": priority,
            "payload": payload or {},
            "max_attempts": max_attempts,
            "request_id": request_id,
        },
    )
    return job


def lease_memory_queue_tasks(
    *,
    job_kinds: list[str] | None = None,
    limit: int = 1,
    lease_seconds: int = 300,
    locked_by: str = "",
):
    """Lease pending/retry-eligible unified-queue tasks.

    Reuses ``DatabaseExternalConnectorQueueBackend.lease`` (ADR-0029 database
    queue backend pattern: ``select_for_update(skip_locked=True)`` on
    PostgreSQL) so the memory queue and the external-connector queue share one
    leasing implementation against ``MemoryExternalConnectorJob``.
    """
    from .external_connectors import DatabaseExternalConnectorQueueBackend

    return DatabaseExternalConnectorQueueBackend().lease(
        limit=limit,
        lease_seconds=lease_seconds,
        locked_by=locked_by,
        job_kinds=job_kinds,
    )


def complete_memory_queue_task(job_id, *, result=None):
    from .external_connectors import DatabaseExternalConnectorQueueBackend

    return DatabaseExternalConnectorQueueBackend().complete(str(job_id), result=result)


def fail_memory_queue_task(job_id, *, error_message: str, retry_delay_seconds: int = 60):
    """Fail a leased task; moves it to ``dead_letter`` once attempts are exhausted."""
    from .external_connectors import DatabaseExternalConnectorQueueBackend

    return DatabaseExternalConnectorQueueBackend().fail(
        str(job_id), error_message=error_message, retry_delay_seconds=retry_delay_seconds
    )


def record_access_audit(
    *,
    actor,
    request_id,
    policy_decision,
    query_hash="",
    returned_document_ids=None,
    returned_fact_ids=None,
    denied_reason="",
    retrieval_trace=None,
):
    return MemoryAccessAudit.objects.create(
        actor=actor,
        request_id=request_id,
        query_hash=query_hash,
        allowed_scope_tokens=sorted(user_scope_tokens(actor)),
        returned_document_ids=returned_document_ids or [],
        returned_fact_ids=returned_fact_ids or [],
        denied_reason=denied_reason,
        policy_decision=policy_decision,
        retrieval_trace=retrieval_trace or {},
    )


def remember_knowledge_for_actor(*, actor, session, payload, request_id=""):
    from .chat_memory import remember_knowledge

    return remember_knowledge(actor=actor, session=session, payload=payload, request_id=request_id)


def update_personal_memory_for_actor(*, actor, payload):
    from .chat_memory import delete_personal_memory, edit_personal_memory

    operation = str(payload.get("operation", "")).strip().lower()
    memory_id = str(payload.get("memory_id", "")).strip()
    if operation == "edit":
        return edit_personal_memory(actor=actor, memory_id=memory_id, new_text=payload.get("new_text", ""))
    if operation == "delete":
        return delete_personal_memory(actor=actor, memory_id=memory_id)
    from django.core.exceptions import ValidationError

    raise ValidationError("operation должен быть 'edit' или 'delete'.")


def _ensure_memory_source_from_envelope(envelope: SourceObjectEnvelope) -> MemorySource:
    config = {
        "source_origin": envelope.source_origin,
        "source_kind": envelope.source_kind,
        "domain": envelope.domain,
        "privacy_profile": envelope.privacy_profile,
        "access_policy": dict(envelope.access_policy or {}),
        "source_adapter": dict(envelope.provenance or {}).get("adapter", envelope.source_code),
        "schema_version": envelope.schema_version,
    }
    source, created = MemorySource.objects.get_or_create(
        code=envelope.source_code,
        defaults={
            "title": _source_title(envelope),
            "source_kind": envelope.source_kind,
            "domain": envelope.domain,
            "owner": str((envelope.provenance or {}).get("owner") or envelope.domain or "system"),
            "status": MemorySource.Status.ENABLED,
            "trust_status": MemorySource.TrustStatus.TRUSTED,
            "authority_class": MemorySource.AuthorityClass.SYSTEM_OF_RECORD,
            "trusted_for_context": True,
            "requires_source_review": False,
            "review_owner": envelope.domain or "system",
            "trusted_context_kinds": ["retrieved_chunk", "citation"],
            "untrusted_handling": "review_required",
            "sync_mode": "manual",
            "scope_rule": "manual_scope_mapping",
            "sensitivity": envelope.sensitivity,
            "pii_policy": envelope.privacy_profile,
            "extractor_profile": "workorder_event_v1",
            "chunking_profile": "short_business_event_v1",
            "index_profiles": ["fulltext_default", "vector_default"],
            "config": config,
        },
    )
    if not created:
        source.status = MemorySource.Status.ENABLED
        source.error_message = ""
        source.sensitivity = envelope.sensitivity
        source.pii_policy = envelope.privacy_profile
        source.config = {**(source.config or {}), **config}
        source.save(update_fields=["status", "error_message", "sensitivity", "pii_policy", "config", "updated_at"])
    return source


def _ensure_memory_source_object_from_envelope(*, source: MemorySource, envelope: SourceObjectEnvelope) -> MemorySourceObject:
    metadata = {
        "schema_version": envelope.schema_version,
        "source_adapter": dict(envelope.provenance or {}).get("adapter", envelope.source_code),
        "object_type": envelope.object_type,
        "title": envelope.title,
        "payload": dict(envelope.payload or {}),
        "relations": [dict(item) for item in envelope.relations],
        "scope_tokens": _envelope_scope_tokens(envelope),
        "privacy_profile": envelope.privacy_profile,
        "access_policy": dict(envelope.access_policy or {}),
        "analytics": dict(envelope.analytics or {}),
        "provenance": dict(envelope.provenance or {}),
    }
    source_object, _created = MemorySourceObject.objects.update_or_create(
        source=source,
        object_id=envelope.object_id,
        defaults={
            "object_uri": f"source-adapter://{envelope.source_code}/{envelope.object_type}/{envelope.object_id}",
            "relative_path": f"{envelope.object_type}/{envelope.object_id}",
            "file_name": envelope.title[:255],
            "extension": "",
            "mime_type": "application/vnd.local-business.source-envelope",
            "size_bytes": len((envelope.text or "").encode("utf-8")),
            "mtime": envelope.source_updated_at,
            "content_hash": envelope.content_hash,
            "last_seen_at": timezone.now(),
            "last_stable_at": timezone.now(),
            "discovery_status": MemorySourceObject.DiscoveryStatus.SEEN,
            "ingestion_status": MemorySourceObject.IngestionStatus.PENDING,
            "metadata": metadata,
        },
    )
    return source_object


def _prepare_source_text_for_index(
    *,
    envelope: SourceObjectEnvelope,
    source: MemorySource,
    source_object: MemorySourceObject,
    privacy_profile,
    dry_run: bool,
) -> dict:
    text = envelope.text or ""
    secret_scan = scan_for_secrets(text)
    issues = []
    if secret_scan.blocked:
        issue = {
            "issue_kind": MemoryIngestionIssue.IssueKind.SECRET_BLOCKED,
            "severity": MemoryIngestionIssue.Severity.BLOCKER,
            "message": secret_scan.reason or "Обнаружены чувствительные учетные данные.",
            "metadata": {
                "source_adapter": True,
                "secret_findings": [
                    {
                        "type": finding.finding_type,
                        "start": finding.start,
                        "end": finding.end,
                        "reason": finding.reason,
                        "confidence": finding.confidence,
                    }
                    for finding in secret_scan.findings
                ],
            },
        }
        if not dry_run:
            _create_projection_issue(source=source, source_object=source_object, **issue)
        return {"blocked": True, "message": issue["message"], "safe_text": "", "pii_findings": (), "issues": [issue]}

    pii_findings = ()
    safe_text = text
    if privacy_profile.detect:
        pii_findings = detect_pii(text, secret_key=settings.SECRET_KEY)
        if pii_findings and privacy_profile.block:
            issue = {
                "issue_kind": MemoryIngestionIssue.IssueKind.PII_BLOCKED,
                "severity": MemoryIngestionIssue.Severity.BLOCKER,
                "message": "Обнаружены данные, похожие на персональные; профиль приватности источника заблокировал обработку.",
                "metadata": {"source_adapter": True, "pii_finding_count": len(pii_findings)},
            }
            if not dry_run:
                _create_projection_issue(source=source, source_object=source_object, **issue)
            return {"blocked": True, "message": issue["message"], "safe_text": "", "pii_findings": pii_findings, "issues": [issue]}
        if pii_findings and privacy_profile.redact_before_index:
            redaction = redact_text(text)
            safe_text = redaction.safe_text
        if pii_findings and privacy_profile.audit:
            issue = {
                "issue_kind": MemoryIngestionIssue.IssueKind.PII_AUDIT,
                "severity": MemoryIngestionIssue.Severity.WARNING,
                "message": "Обнаружены данные, похожие на персональные; объект источника проиндексирован согласно профилю приватности.",
                "metadata": {"source_adapter": True, "pii_finding_count": len(pii_findings)},
            }
            issues.append(issue)
            if not dry_run:
                _create_projection_issue(source=source, source_object=source_object, **issue)

    return {"blocked": False, "message": "", "safe_text": safe_text, "pii_findings": pii_findings, "issues": issues}


def _create_projection_issue(*, source, source_object, issue_kind, severity, message, metadata):
    return MemoryIngestionIssue.objects.create(
        source=source,
        source_object=source_object,
        issue_kind=issue_kind,
        severity=severity,
        message=message,
        metadata=metadata,
    )


def _memory_document_metadata(
    *,
    envelope: SourceObjectEnvelope,
    source: MemorySource,
    source_object: MemorySourceObject,
    safe_text: str,
    pii_findings,
) -> dict:
    vector_backend = get_default_vector_backend()
    embedding_metadata = vector_backend.embedding_provider.metadata if vector_backend is not None else None
    return {
        "source_adapter": dict(envelope.provenance or {}).get("adapter", envelope.source_code),
        "schema_version": envelope.schema_version,
        "object_type": envelope.object_type,
        "title": envelope.title,
        "source_object_id": source_object.object_id,
        "content_hash": envelope.content_hash,
        "sensitivity": envelope.sensitivity,
        "privacy_profile": envelope.privacy_profile,
        "access_policy": dict(envelope.access_policy or {}),
        "payload_keys": sorted((envelope.payload or {}).keys()),
        "raw_mode": "source_of_truth_reference",
        "index_versions": {
            "fulltext": get_default_fulltext_schema_version(),
            **({"vector": LANCEDB_VECTOR_SCHEMA_VERSION} if vector_backend is not None else {}),
        },
        "embedding": embedding_metadata.__dict__ if embedding_metadata is not None else {},
        "pii_detected": bool(pii_findings),
        "pii_finding_count": len(pii_findings),
        "safe_text_hash": sha256_text(safe_text),
        "trust_status": source.trust_status,
        "authority_class": source.authority_class,
    }


def _upsert_projection_indexes(
    *,
    document: MemorySearchDocument,
    envelope: SourceObjectEnvelope,
    safe_text: str,
    metadata: dict,
    index_backends: Iterable[str],
) -> None:
    selected_backends = set(index_backends or ())
    record = MemoryIndexRecord(
        document_id=document.document_id,
        text="\n".join(value for value in (envelope.title, envelope.object_id, safe_text) if value),
        metadata={
            **metadata,
            "corpus_type": "source_data",
            "result_type": "source_data",
            "source_code": envelope.source_code,
            "source_kind": envelope.source_kind,
            "source_object_id": envelope.object_id,
            "content_hash": envelope.content_hash,
        },
        scope_tokens=_envelope_scope_tokens(envelope),
        sensitivity=envelope.sensitivity,
        is_active=True,
    )
    if "fulltext" in selected_backends:
        get_default_backend().upsert(record)
    if "vector" in selected_backends:
        vector_backend = get_default_vector_backend()
        if vector_backend is not None:
            vector_backend.upsert(record)


def _envelope_scope_tokens(envelope: SourceObjectEnvelope) -> list[str]:
    return sorted({str(token) for token in (envelope.access_policy or {}).get("scope_tokens", []) if str(token).strip()})


def _source_title(envelope: SourceObjectEnvelope) -> str:
    return str((envelope.provenance or {}).get("source_title") or envelope.source_code).replace("_", " ").title()


def sha256_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()
