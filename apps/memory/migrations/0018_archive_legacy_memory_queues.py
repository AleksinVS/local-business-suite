# ADR-0030 decision 2 (packet 02): collapse MemoryWriteRequest / MemoryIndexJob /
# MemoryKnowledgeEvent / MemoryReflectionRun into the single MemoryExternalConnectorJob
# queue. This data migration runs BEFORE the schema migration that drops the four
# tables: it archives every row to a JSON dump under
# ``<DATA_DIR>/memory/queue_archive/<table>.json`` and re-enqueues any unfinished
# write/index work as tasks in the unified queue so no in-flight work is lost.
#
# It also nulls out MemoryReviewAction.index_job (which pointed at MemoryIndexJob)
# so the following schema migration can safely repoint that foreign key at
# MemoryExternalConnectorJob.
from __future__ import annotations

import json
import uuid
from pathlib import Path

from django.conf import settings
from django.db import migrations


def _archive_dir() -> Path:
    return Path(settings.DATA_DIR) / "memory" / "queue_archive"


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _row_to_dict(instance) -> dict:
    row = {}
    for field in instance._meta.fields:
        row[field.name] = _json_safe(field.value_from_object(instance))
    return row


def _dump_archive(*, name: str, rows: list[dict]) -> None:
    directory = _archive_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.json"
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        # Archival is best-effort: a read-only filesystem must not block the
        # schema migration that follows. The unified-queue re-enqueue below is
        # unaffected because it only touches the database.
        pass


def archive_and_migrate_legacy_queues(apps, schema_editor):
    MemoryWriteRequest = apps.get_model("memory", "MemoryWriteRequest")
    MemoryIndexJob = apps.get_model("memory", "MemoryIndexJob")
    MemoryKnowledgeEvent = apps.get_model("memory", "MemoryKnowledgeEvent")
    MemoryReflectionRun = apps.get_model("memory", "MemoryReflectionRun")
    MemoryExternalConnectorJob = apps.get_model("memory", "MemoryExternalConnectorJob")
    MemoryReviewAction = apps.get_model("memory", "MemoryReviewAction")

    write_requests = list(MemoryWriteRequest.objects.all().order_by("id"))
    index_jobs = list(MemoryIndexJob.objects.all().order_by("id"))
    knowledge_events = list(MemoryKnowledgeEvent.objects.all().order_by("id"))
    reflection_runs = list(MemoryReflectionRun.objects.all().order_by("id"))

    _dump_archive(name="memory_write_request", rows=[_row_to_dict(row) for row in write_requests])
    _dump_archive(name="memory_index_job", rows=[_row_to_dict(row) for row in index_jobs])
    _dump_archive(name="memory_knowledge_event", rows=[_row_to_dict(row) for row in knowledge_events])
    _dump_archive(name="memory_reflection_run", rows=[_row_to_dict(row) for row in reflection_runs])

    unfinished_request_statuses = {"queued", "processing", "failed"}
    for request in write_requests:
        if request.status not in unfinished_request_statuses:
            continue
        idempotency_key = f"legacy-write-request:{request.request_id}"
        if MemoryExternalConnectorJob.objects.filter(idempotency_key=idempotency_key).exists():
            continue
        MemoryExternalConnectorJob.objects.create(
            source_code="",
            job_kind="ingestion",
            status="pending",
            priority=0,
            payload={
                "legacy": "memory_write_request",
                "request_id": str(request.request_id),
                "actor_id": request.actor_id,
                "session_id": request.session_id,
                "message_ids": request.message_ids,
                "target_scope": request.target_scope,
                "user_note": request.user_note,
                "importance": request.importance,
            },
            idempotency_key=idempotency_key,
            max_attempts=3,
            request_id=str(request.request_id),
        )

    # REMEMBER-kind index jobs are pure orchestration wrappers around a
    # MemoryWriteRequest that is already migrated above; skip them here to
    # avoid enqueuing the same write twice.
    unfinished_index_statuses = {"pending", "running", "failed"}
    reindexable_kinds = {"discover", "sync", "reindex", "eval"}
    for job in index_jobs:
        if job.status not in unfinished_index_statuses or job.job_kind not in reindexable_kinds:
            continue
        idempotency_key = f"legacy-index-job:{job.pk}"
        if MemoryExternalConnectorJob.objects.filter(idempotency_key=idempotency_key).exists():
            continue
        MemoryExternalConnectorJob.objects.create(
            source_code=getattr(job.source, "code", "") or "",
            job_kind="reindex",
            status="pending",
            priority=0,
            payload={
                "legacy": "memory_index_job",
                "legacy_job_id": job.pk,
                "legacy_job_kind": job.job_kind,
                **(job.payload or {}),
            },
            idempotency_key=idempotency_key,
            max_attempts=3,
            request_id=job.request_id or "",
        )

    MemoryReviewAction.objects.exclude(index_job__isnull=True).update(index_job=None)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("memory", "0017_memoryexternalconnectorjob_memoryfulltextindex"),
    ]

    operations = [
        migrations.RunPython(archive_and_migrate_legacy_queues, noop),
    ]
