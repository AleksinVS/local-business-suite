from django.contrib import admin
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    MemoryAccessAudit,
    MemoryChunk,
    MemoryEvalCase,
    MemoryGraphFact,
    MemoryIndexJob,
    MemorySnapshot,
    MemorySource,
)


@admin.register(MemorySource)
class MemorySourceAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "title",
        "domain",
        "source_kind",
        "status",
        "sensitivity",
        "snapshot_count",
        "blocked_snapshot_count",
        "job_count",
        "last_synced_at",
        "updated_at",
    )
    list_filter = ("status", "domain", "source_kind", "sensitivity", "sync_mode")
    search_fields = ("code", "title", "owner")
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                _snapshot_count=Count("snapshots", distinct=True),
                _blocked_snapshot_count=Count(
                    "snapshots",
                    filter=Q(snapshots__status=MemorySnapshot.Status.BLOCKED),
                    distinct=True,
                ),
                _job_count=Count("index_jobs", distinct=True),
            )
        )

    @admin.display(ordering="_snapshot_count", description="Snapshots")
    def snapshot_count(self, obj):
        return obj._snapshot_count

    @admin.display(ordering="_blocked_snapshot_count", description="Blocked")
    def blocked_snapshot_count(self, obj):
        return obj._blocked_snapshot_count

    @admin.display(ordering="_job_count", description="Jobs")
    def job_count(self, obj):
        return obj._job_count


@admin.register(MemorySnapshot)
class MemorySnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "source_object_id",
        "short_content_hash",
        "status",
        "is_active",
        "sensitivity",
        "chunk_count",
        "blocked_reason_short",
        "extracted_at",
    )
    list_filter = ("status", "is_active", "sensitivity", "source__domain", "source__source_kind", "extracted_at")
    search_fields = ("source__code", "source_object_id", "content_hash", "blocked_reason")
    readonly_fields = ("created_at", "updated_at", "storage_state")
    autocomplete_fields = ("source",)
    fieldsets = (
        (None, {"fields": ("source", "source_object_id", "content_hash", "schema_version", "extractor_version")}),
        ("Lifecycle", {"fields": ("status", "is_active", "extracted_at", "valid_from", "valid_to")}),
        (
            "Privacy",
            {"fields": ("sensitivity", "pii_policy_applied", "blocked_reason", "scope_tokens", "storage_state")},
        ),
        ("Metadata", {"fields": ("metadata", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("source")
            .annotate(_chunk_count=Count("chunks", distinct=True))
        )

    def has_add_permission(self, request):
        return False

    @admin.display(ordering="content_hash", description="Content hash")
    def short_content_hash(self, obj):
        return obj.content_hash[:12]

    @admin.display(ordering="_chunk_count", description="Chunks")
    def chunk_count(self, obj):
        return obj._chunk_count

    @admin.display(description="Blocked reason")
    def blocked_reason_short(self, obj):
        if not obj.blocked_reason:
            return ""
        return obj.blocked_reason[:96]

    @admin.display(description="Stored artifacts")
    def storage_state(self, obj):
        raw_state = "raw: present" if obj.raw_path else "raw: missing"
        safe_state = "safe: present" if obj.safe_path else "safe: missing"
        return f"{raw_state}; {safe_state}"


@admin.register(MemoryChunk)
class MemoryChunkAdmin(admin.ModelAdmin):
    list_display = (
        "chunk_id",
        "source_code",
        "source_object_id",
        "position",
        "is_active",
        "sensitivity",
        "text_hash",
        "graph_fact_count",
    )
    list_filter = ("is_active", "sensitivity", "source_code", "snapshot__status", "snapshot__source__domain")
    search_fields = ("chunk_id", "source_code", "source_object_id", "snapshot_hash", "text_hash")
    readonly_fields = ("created_at", "updated_at", "storage_state")
    autocomplete_fields = ("snapshot",)
    fieldsets = (
        (None, {"fields": ("snapshot", "chunk_id", "source_code", "source_object_id", "snapshot_hash", "position")}),
        ("Index metadata", {"fields": ("text_hash", "metadata", "scope_tokens", "sensitivity", "storage_state")}),
        ("Lifecycle", {"fields": ("is_active", "valid_from", "valid_to", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("snapshot", "snapshot__source")
            .annotate(_graph_fact_count=Count("graph_facts"))
        )

    def has_add_permission(self, request):
        return False

    @admin.display(ordering="_graph_fact_count", description="Facts")
    def graph_fact_count(self, obj):
        return obj._graph_fact_count

    @admin.display(description="Stored artifact")
    def storage_state(self, obj):
        return "text: present" if obj.text_path else "text: missing"


@admin.register(MemoryGraphFact)
class MemoryGraphFactAdmin(admin.ModelAdmin):
    list_display = (
        "fact_id",
        "source_code",
        "subject_id",
        "predicate",
        "object_id",
        "confidence",
        "is_active",
        "sensitivity",
    )
    list_filter = ("predicate", "is_active", "sensitivity", "snapshot__source__domain")
    search_fields = ("fact_id", "subject_id", "predicate", "object_id", "snapshot_hash")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source_chunk", "snapshot")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("snapshot", "snapshot__source", "source_chunk")

    @admin.display(ordering="snapshot__source__code", description="Source")
    def source_code(self, obj):
        return obj.snapshot.source.code


@admin.register(MemoryIndexJob)
class MemoryIndexJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "job_kind",
        "status",
        "source",
        "request_id",
        "attempts_display",
        "created_by",
        "created_at",
        "started_at",
        "finished_at",
        "duration",
    )
    list_filter = ("job_kind", "status", "source__domain", "created_at", "started_at", "finished_at")
    search_fields = ("request_id", "source__code", "error_message")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source", "created_by")
    actions = ("cancel_selected_jobs",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("source", "created_by")

    @admin.display(description="Attempts")
    def attempts_display(self, obj):
        return f"{obj.attempts}/{obj.max_attempts}"

    @admin.display(description="Duration")
    def duration(self, obj):
        if not obj.started_at:
            return ""
        finished_at = obj.finished_at or timezone.now()
        return finished_at - obj.started_at

    @admin.action(description="Cancel selected pending/running jobs")
    def cancel_selected_jobs(self, request, queryset):
        now = timezone.now()
        updated = queryset.filter(status__in=[MemoryIndexJob.Status.PENDING, MemoryIndexJob.Status.RUNNING]).update(
            status=MemoryIndexJob.Status.CANCELLED,
            finished_at=now,
            updated_at=now,
        )
        self.message_user(request, f"Cancelled {updated} pending/running memory job(s).")


@admin.register(MemoryAccessAudit)
class MemoryAccessAuditAdmin(admin.ModelAdmin):
    list_display = (
        "request_id",
        "actor",
        "tool_name",
        "policy_decision",
        "returned_chunks_count",
        "returned_facts_count",
        "denied_reason_short",
        "created_at",
    )
    list_filter = ("policy_decision", "tool_name", "actor", "created_at")
    search_fields = ("request_id", "actor__username", "query_hash")
    readonly_fields = (
        "actor",
        "request_id",
        "query_hash",
        "tool_name",
        "allowed_scope_tokens",
        "returned_chunk_ids",
        "returned_fact_ids",
        "denied_reason",
        "policy_decision",
        "retrieval_trace",
        "created_at",
    )
    autocomplete_fields = ("actor",)
    fieldsets = (
        (None, {"fields": ("actor", "request_id", "tool_name", "policy_decision", "query_hash")}),
        (
            "Retrieval",
            {"fields": ("returned_chunk_ids", "returned_fact_ids", "allowed_scope_tokens", "retrieval_trace")},
        ),
        ("Denied access", {"fields": ("denied_reason",)}),
        ("Timestamps", {"fields": ("created_at",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("actor")

    def has_add_permission(self, request):
        return False

    @admin.display(description="Chunks")
    def returned_chunks_count(self, obj):
        return len(obj.returned_chunk_ids or [])

    @admin.display(description="Facts")
    def returned_facts_count(self, obj):
        return len(obj.returned_fact_ids or [])

    @admin.display(description="Denied reason")
    def denied_reason_short(self, obj):
        if not obj.denied_reason:
            return ""
        return obj.denied_reason[:96]


@admin.register(MemoryEvalCase)
class MemoryEvalCaseAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "suite", "status", "updated_at")
    list_filter = ("suite", "status")
    search_fields = ("code", "title", "question")
    readonly_fields = ("created_at", "updated_at")
