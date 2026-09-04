"""Actor-aware, fail-closed selectors for the memory read contour."""

from django.db.models import Q

from .models import MemoryExternalConnectorJob, MemorySearchDocument, MemorySource, MemorySourceObject
from .policies import (
    can_access_search_document,
    resolve_active_actor,
    scope_tokens_match,
    source_scope_tokens,
    user_scope_tokens,
)
from .config_documents import get_memory_document_snapshots


def memory_sources_queryset(actor=None):
    """Return only enabled sources visible to the supplied actor."""

    actor = resolve_active_actor(actor, force_refresh=True)
    queryset = MemorySource.objects.filter(status=MemorySource.Status.ENABLED)
    if actor is None:
        return queryset.none()
    if getattr(actor, "is_superuser", False):
        return queryset
    tokens = user_scope_tokens(actor)
    if not tokens:
        return queryset.none()
    visible_ids = [
        source.pk
        for source in queryset.only("id", "status", "scope_rule", "config")
        if (source.config or {}).get("access_policy", {}).get("mode") != "adapter_check"
        and scope_tokens_match(source_scope_tokens(source), tokens)
    ]
    return queryset.filter(pk__in=visible_ids)


def active_sources_queryset(actor=None):
    # Keep the legacy name, but do not make it an unscoped source oracle.
    return memory_sources_queryset(actor)


def search_documents_for_source_queryset(source, actor=None):
    actor = resolve_active_actor(actor, force_refresh=True)
    queryset = MemorySearchDocument.objects.filter(
        source_object__source=source,
        source_object__source__status=MemorySource.Status.ENABLED,
    ).select_related("knowledge_item", "source_object", "source_object__source")
    if actor is None or source is None:
        return queryset.none()
    fresh_source = MemorySource.objects.filter(pk=source.pk, status=MemorySource.Status.ENABLED).first()
    if fresh_source is None:
        return queryset.none()
    if getattr(actor, "is_superuser", False):
        return queryset
    snapshots = get_memory_document_snapshots(
        document_ids=("memory.contract.ingestion_profiles",)
    )
    visible_ids = [
        document.pk
        for document in queryset
        if can_access_search_document(actor, document, snapshots=snapshots)
    ]
    return queryset.filter(pk__in=visible_ids)


def active_search_documents_queryset(actor=None):
    actor = resolve_active_actor(actor, force_refresh=True)
    queryset = MemorySearchDocument.objects.filter(
        index_status=MemorySearchDocument.IndexStatus.READY,
    ).filter(
        Q(source_object__isnull=True)
        | Q(source_object__source__status=MemorySource.Status.ENABLED)
    ).select_related("knowledge_item", "source_object", "source_object__source")
    if actor is None:
        return queryset.none()
    if getattr(actor, "is_superuser", False):
        return queryset
    snapshots = get_memory_document_snapshots(
        document_ids=("memory.contract.ingestion_profiles",)
    )
    visible_ids = [
        document.pk
        for document in queryset
        if can_access_search_document(actor, document, snapshots=snapshots)
    ]
    return queryset.filter(pk__in=visible_ids)


def recent_index_jobs_queryset(actor=None, limit=50):
    """Return only queue jobs whose source/object is visible to ``actor``."""

    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None:
        return []
    jobs = MemoryExternalConnectorJob.objects.exclude(source_code="").order_by("-created_at", "-id")[:limit]
    snapshots = get_memory_document_snapshots(
        document_ids=("memory.contract.ingestion_profiles",)
    )
    return [job for job in jobs if _job_visible_to_actor(job, actor, snapshots=snapshots)]


def _job_visible_to_actor(job, actor, *, snapshots=None) -> bool:
    source = MemorySource.objects.filter(
        code=job.source_code,
        status=MemorySource.Status.ENABLED,
    ).first()
    if source is None:
        return False
    payload = job.payload or {}
    source_object_id = payload.get("source_object_id")
    if source_object_id:
        source_object = MemorySourceObject.objects.select_related("source").filter(
            source=source,
            object_id=str(source_object_id),
        ).first()
        if source_object is None:
            return False
        from .services import can_access_source_object

        return can_access_source_object(actor, source_object, snapshots=snapshots)
    document_id = payload.get("document_id")
    if document_id:
        document = MemorySearchDocument.objects.select_related("source_object", "source_object__source").filter(
            document_id=str(document_id),
            source_object__source=source,
        ).first()
        return document is not None and can_access_search_document(
            actor,
            document,
            snapshots=snapshots,
        )
    if getattr(actor, "is_superuser", False):
        return True
    if (source.config or {}).get("access_policy", {}).get("mode") == "adapter_check":
        return False
    return scope_tokens_match(source_scope_tokens(source), user_scope_tokens(actor))
