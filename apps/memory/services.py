from django.utils import timezone

from .knowledge_files import read_knowledge_item_file
from .models import MemoryAccessAudit, MemoryIndexJob, MemoryKnowledgeItem, MemorySource
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
