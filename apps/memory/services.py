from django.utils import timezone

from .models import MemoryAccessAudit, MemoryClaim, MemoryIndexJob, MemoryKnowledgeItem, MemorySource
from .policies import user_scope_tokens


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


def create_claim_for_knowledge_item(*, item: MemoryKnowledgeItem, created_by=None, status=None):
    from .chat_memory import _sha256

    actor = created_by or item.created_by
    claim_status = status or MemoryClaim.Status.ACCEPTED
    evidence = [
        {
            "kind": "memory_knowledge_item",
            "memory_id": item.memory_id,
            "source_content_hash": item.source_content_hash,
            "source_message_ids": item.source_message_ids,
        }
    ]
    claim_id = f"claim:{_sha256(item.memory_id + ':' + item.text)[:32]}"
    claim, _ = MemoryClaim.objects.update_or_create(
        claim_id=claim_id,
        defaults={
            "claim_type": _claim_type_for_knowledge_kind(item.kind),
            "text": item.text,
            "payload": {
                "memory_id": item.memory_id,
                "scope": item.scope,
                "kind": item.kind,
            },
            "status": claim_status,
            "confidence": "1.0000" if claim_status == MemoryClaim.Status.ACCEPTED else "0.5000",
            "knowledge_item": item,
            "evidence": evidence,
            "evidence_hash": _sha256(str(evidence)),
            "scope_tokens": item.scope_tokens,
            "sensitivity": item.sensitivity,
            "observed_at": item.updated_at,
            "reviewer": actor if item.scope == MemoryKnowledgeItem.Scope.ORGANIZATION else None,
            "reviewed_at": timezone.now() if item.scope == MemoryKnowledgeItem.Scope.ORGANIZATION else None,
            "decision_note": "Accepted from explicit chat memory write." if claim_status == MemoryClaim.Status.ACCEPTED else "",
            "metadata": {
                "source": "chat_memory",
                "secret_handles": (item.metadata or {}).get("secret_handles", []),
            },
            "created_by": actor,
        },
    )
    return claim


def compile_knowledge_item_digest(*, scope_tokens=None, limit=100):
    queryset = MemoryKnowledgeItem.objects.filter(status=MemoryKnowledgeItem.Status.ACTIVE).order_by("-updated_at", "-id")
    tokens = set(scope_tokens or [])
    records = []
    for item in queryset[: max(int(limit), 1)]:
        if tokens and not set(item.scope_tokens or []) & tokens:
            continue
        records.append(
            {
                "memory_id": item.memory_id,
                "text": item.text,
                "scope": item.scope,
                "scope_tokens": item.scope_tokens,
                "sensitivity": item.sensitivity,
                "updated_at": item.updated_at.isoformat(),
            }
        )
    return records


def create_index_job(*, job_kind, source=None, created_by=None, request_id="", payload=None):
    return MemoryIndexJob.objects.create(
        source=source,
        job_kind=job_kind,
        created_by=created_by,
        request_id=request_id,
        payload=payload or {},
    )


def mark_index_job_started(job: MemoryIndexJob):
    job.status = MemoryIndexJob.Status.RUNNING
    job.started_at = timezone.now()
    job.attempts += 1
    job.save(update_fields=["status", "started_at", "attempts", "updated_at"])
    return job


def mark_index_job_finished(job: MemoryIndexJob, *, result=None):
    job.status = MemoryIndexJob.Status.SUCCEEDED
    job.finished_at = timezone.now()
    job.result = result or {}
    job.error_message = ""
    job.save(update_fields=["status", "finished_at", "result", "error_message", "updated_at"])
    return job


def mark_index_job_failed(job: MemoryIndexJob, *, error_message, result=None):
    job.status = MemoryIndexJob.Status.FAILED
    job.finished_at = timezone.now()
    job.error_message = error_message
    job.result = result or {}
    job.save(update_fields=["status", "finished_at", "error_message", "result", "updated_at"])
    return job


def record_access_audit(
    *,
    actor,
    request_id,
    policy_decision,
    query_hash="",
    returned_chunk_ids=None,
    returned_fact_ids=None,
    denied_reason="",
    retrieval_trace=None,
):
    return MemoryAccessAudit.objects.create(
        actor=actor,
        request_id=request_id,
        query_hash=query_hash,
        allowed_scope_tokens=sorted(user_scope_tokens(actor)),
        returned_chunk_ids=returned_chunk_ids or [],
        returned_fact_ids=returned_fact_ids or [],
        denied_reason=denied_reason,
        policy_decision=policy_decision,
        retrieval_trace=retrieval_trace or {},
    )


def apply_snapshot_privacy_pipeline(*, snapshot, text, secret_key):
    from .deidentification import deidentify_text
    from .models import MemorySnapshot

    result = deidentify_text(text or "", secret_key=secret_key)
    snapshot.pii_policy_applied = snapshot.pii_policy_applied or snapshot.source.pii_policy or "deidentify_before_index"

    if result.blocked:
        snapshot.status = MemorySnapshot.Status.BLOCKED
        snapshot.blocked_reason = result.reason
        snapshot.save(update_fields=["status", "blocked_reason", "pii_policy_applied", "updated_at"])
        return result

    snapshot.status = MemorySnapshot.Status.READY
    snapshot.blocked_reason = ""
    snapshot.save(update_fields=["status", "blocked_reason", "pii_policy_applied", "updated_at"])
    return result


def index_ready_snapshot_text(*, snapshot, safe_text, vector_backend=None, graph_backend=None, chunk_size=None, chunk_overlap=None):
    from .ingestion import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, index_snapshot_text

    return index_snapshot_text(
        snapshot=snapshot,
        safe_text=safe_text,
        vector_backend=vector_backend,
        graph_backend=graph_backend,
        chunk_size=chunk_size or DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP if chunk_overlap is None else chunk_overlap,
    )


def deactivate_snapshot_memory_indexes(*, snapshot):
    from .ingestion import deactivate_snapshot_indexes

    deactivate_snapshot_indexes(snapshot=snapshot)


def queue_memory_remember_for_actor(*, actor, session, payload, request_id=""):
    from .chat_memory import queue_memory_remember

    return queue_memory_remember(actor=actor, session=session, payload=payload, request_id=request_id)


def update_personal_memory_for_actor(*, actor, payload):
    from .chat_memory import delete_personal_memory, edit_personal_memory

    operation = str(payload.get("operation", "")).strip().lower()
    memory_id = str(payload.get("memory_id", "")).strip()
    if operation == "edit":
        return edit_personal_memory(actor=actor, memory_id=memory_id, new_text=payload.get("new_text", ""))
    if operation == "delete":
        return delete_personal_memory(actor=actor, memory_id=memory_id)
    from django.core.exceptions import ValidationError

    raise ValidationError("operation must be 'edit' or 'delete'.")


def _claim_type_for_knowledge_kind(kind: str) -> str:
    mapping = {
        MemoryKnowledgeItem.Kind.FACT: MemoryClaim.ClaimType.FACT,
        MemoryKnowledgeItem.Kind.PREFERENCE: MemoryClaim.ClaimType.PREFERENCE,
        MemoryKnowledgeItem.Kind.PROCEDURE: MemoryClaim.ClaimType.PROCEDURE,
        MemoryKnowledgeItem.Kind.DECISION: MemoryClaim.ClaimType.DECISION,
        MemoryKnowledgeItem.Kind.SECRET_REFERENCE: MemoryClaim.ClaimType.FACT,
    }
    return mapping.get(kind, MemoryClaim.ClaimType.FACT)
