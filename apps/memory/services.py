from django.utils import timezone

from .models import MemoryAccessAudit, MemoryIndexJob, MemorySource
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
