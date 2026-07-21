"""Single worker for the unified memory background queue (ADR-0030 decision 2).

Processes ``reconcile``/``ingestion``/``reindex`` tasks queued on
``MemoryExternalConnectorJob`` (the same table the external-connector pipeline
uses). Retryable failures go back to ``retry_wait``; once ``max_attempts`` is
exhausted the task moves to ``dead_letter`` where it is visible to an operator
via ``memory_external_queue_status`` / the admin.
"""
from __future__ import annotations

import os
import socket

from django.core.management.base import BaseCommand
from django.core.management import call_command

from apps.memory.chat_memory import index_knowledge_item, remember_knowledge
from apps.memory.models import MemoryKnowledgeItem
from apps.memory.services import (
    MemoryQueueJobKind,
    complete_memory_queue_task,
    fail_memory_queue_task,
    lease_memory_queue_tasks,
)

QUEUE_JOB_KINDS = (
    MemoryQueueJobKind.RECONCILE,
    MemoryQueueJobKind.INGESTION,
    MemoryQueueJobKind.REINDEX,
)


class Command(BaseCommand):
    help = "Process reconcile/ingestion/reindex tasks from the unified memory queue."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10, help="Maximum tasks to lease and process.")
        parser.add_argument("--lease-seconds", type=int, default=300, help="Lease duration for running tasks.")
        parser.add_argument("--dry-run", action="store_true", help="Show that the worker is available without leasing tasks.")

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"]))
        lease_seconds = max(30, int(options["lease_seconds"]))
        if options["dry_run"]:
            self.stdout.write(f"Memory queue worker dry-run: limit={limit}, lease_seconds={lease_seconds}")
            return

        locked_by = f"memory_queue_worker:{socket.gethostname()}:{os.getpid()}"
        leased = lease_memory_queue_tasks(
            job_kinds=list(QUEUE_JOB_KINDS),
            limit=limit,
            lease_seconds=lease_seconds,
            locked_by=locked_by,
        )
        succeeded = 0
        failed = 0
        for job in leased:
            try:
                result = _process_task(job)
                complete_memory_queue_task(job.job_id, result=result)
                succeeded += 1
            except Exception as exc:
                fail_memory_queue_task(job.job_id, error_message=str(exc))
                failed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Memory queue worker finished: leased={len(leased)}, succeeded={succeeded}, failed={failed}"
            )
        )


def _process_task(job) -> dict:
    if job.job_kind == MemoryQueueJobKind.REINDEX:
        return _process_reindex(job.payload or {})
    if job.job_kind == MemoryQueueJobKind.INGESTION:
        return _process_ingestion(job.payload or {})
    if job.job_kind == MemoryQueueJobKind.RECONCILE:
        return _process_reconcile(job.payload or {})
    raise ValueError(f"Unsupported memory queue job kind: {job.job_kind}")


def _process_reindex(payload: dict) -> dict:
    memory_id = payload.get("memory_id")
    if not memory_id:
        # Legacy source-data reindex task migrated from MemoryIndexJob: there is
        # no single knowledge item to target, so fall back to a full reconcile
        # pass, which regenerates search documents from the knowledge/source
        # canon.
        return _process_reconcile(payload)
    item = MemoryKnowledgeItem.objects.get(memory_id=memory_id)
    index_knowledge_item(item)
    return {"memory_id": memory_id, "indexed": True}


def _process_ingestion(payload: dict) -> dict:
    """Replay a legacy ``MemoryWriteRequest`` that was still queued when packet 02 shipped."""
    from django.contrib.auth import get_user_model
    from apps.ai.models import ChatSession

    User = get_user_model()
    actor = User.objects.get(pk=payload["actor_id"])
    session = ChatSession.objects.get(pk=payload["session_id"]) if payload.get("session_id") else None
    result = remember_knowledge(
        actor=actor,
        session=session,
        payload={
            "message_ids": payload.get("message_ids") or [],
            "target_scope": payload.get("target_scope"),
            "user_note": payload.get("user_note", ""),
            "importance": payload.get("importance", ""),
        },
        request_id=payload.get("request_id", ""),
    )
    return result


def _process_reconcile(payload: dict) -> dict:
    call_command("memory_reconcile")
    return {"reconciled": True}
