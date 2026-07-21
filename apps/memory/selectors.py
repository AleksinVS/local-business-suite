from .models import MemoryExternalConnectorJob, MemorySearchDocument, MemorySource
from .policies import can_access_search_document


def memory_sources_queryset():
    return MemorySource.objects.all()


def active_sources_queryset():
    return memory_sources_queryset().filter(status=MemorySource.Status.ENABLED)


def search_documents_for_source_queryset(source):
    return MemorySearchDocument.objects.filter(source_object__source=source).select_related("knowledge_item", "source_object", "source_object__source")


def active_search_documents_queryset(user):
    queryset = MemorySearchDocument.objects.filter(index_status=MemorySearchDocument.IndexStatus.READY).select_related(
        "knowledge_item",
        "source_object",
        "source_object__source",
    )
    if getattr(user, "is_superuser", False):
        return queryset
    return [document for document in queryset if can_access_search_document(user, document)]


def recent_index_jobs_queryset(limit=50):
    return MemoryExternalConnectorJob.objects.order_by("-created_at", "-id")[:limit]
