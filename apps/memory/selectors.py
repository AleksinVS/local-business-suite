from .models import MemoryChunk, MemoryGraphFact, MemoryIndexJob, MemorySnapshot, MemorySource
from .policies import can_access_chunk, can_access_graph_fact


def memory_sources_queryset():
    return MemorySource.objects.all()


def active_sources_queryset():
    return memory_sources_queryset().filter(status=MemorySource.Status.ENABLED)


def snapshots_for_source_queryset(source):
    return MemorySnapshot.objects.filter(source=source).select_related("source")


def active_chunks_queryset(user):
    queryset = MemoryChunk.objects.filter(is_active=True).select_related("snapshot", "snapshot__source")
    if getattr(user, "is_superuser", False):
        return queryset
    return [chunk for chunk in queryset if can_access_chunk(user, chunk)]


def active_graph_facts_queryset(user):
    queryset = MemoryGraphFact.objects.filter(is_active=True).select_related("source_chunk", "snapshot", "snapshot__source")
    if getattr(user, "is_superuser", False):
        return queryset
    return [fact for fact in queryset if can_access_graph_fact(user, fact)]


def recent_index_jobs_queryset(limit=50):
    return MemoryIndexJob.objects.select_related("source", "created_by").order_by("-created_at", "-id")[:limit]
