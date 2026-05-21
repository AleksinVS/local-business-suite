from django.contrib import admin
from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    MemoryAccessAudit,
    MemoryChunk,
    MemoryClaim,
    MemoryEvalCase,
    MemoryGraphEntity,
    MemoryGraphExtractionRun,
    MemoryGraphFact,
    MemoryGraphReviewItem,
    MemoryGraphSchemaProposal,
    MemoryIngestionIssue,
    MemoryIngestionRun,
    MemoryIndexJob,
    MemoryKnowledgeCandidate,
    MemoryKnowledgeEvent,
    MemoryKnowledgeItem,
    MemoryReflectionRun,
    MemorySnapshot,
    MemorySource,
    MemorySourceObject,
    MemoryWriteRequest,
    SecretAccessAudit,
    SecretHandle,
)


@admin.register(MemorySource)
class MemorySourceAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "title",
        "domain",
        "source_kind",
        "status",
        "trust_status",
        "authority_class",
        "trusted_for_context",
        "sensitivity",
        "snapshot_count",
        "blocked_snapshot_count",
        "job_count",
        "last_synced_at",
        "updated_at",
    )
    list_filter = (
        "status",
        "trust_status",
        "authority_class",
        "trusted_for_context",
        "domain",
        "source_kind",
        "sensitivity",
        "sync_mode",
    )
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


@admin.register(MemorySourceObject)
class MemorySourceObjectAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "relative_path",
        "discovery_status",
        "ingestion_status",
        "size_bytes",
        "short_content_hash",
        "last_seen_at",
        "last_ingested_at",
    )
    list_filter = ("discovery_status", "ingestion_status", "source__domain", "extension", "last_seen_at")
    search_fields = ("source__code", "object_id", "relative_path", "file_name", "content_hash")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("source")

    @admin.display(ordering="content_hash", description="Content hash")
    def short_content_hash(self, obj):
        return (obj.content_hash or "")[:12]


@admin.register(MemoryIngestionRun)
class MemoryIngestionRunAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "status", "dry_run", "started_at", "finished_at", "issue_count", "created_at")
    list_filter = ("status", "dry_run", "source__domain", "created_at", "started_at")
    search_fields = ("source__code", "error_message")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source", "created_by")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("source", "created_by").annotate(_issue_count=Count("issues"))

    @admin.display(ordering="_issue_count", description="Issues")
    def issue_count(self, obj):
        return obj._issue_count


@admin.register(MemoryIngestionIssue)
class MemoryIngestionIssueAdmin(admin.ModelAdmin):
    list_display = ("issue_kind", "status", "severity", "source", "source_object_display", "message_short", "created_at")
    list_filter = ("issue_kind", "status", "severity", "source__domain", "created_at")
    search_fields = ("source__code", "source_object__relative_path", "message")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source", "source_object", "run")
    actions = ("acknowledge_selected", "resolve_selected", "ignore_selected")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("source", "source_object", "run")

    @admin.display(description="Object")
    def source_object_display(self, obj):
        return obj.source_object.relative_path if obj.source_object_id else ""

    @admin.display(description="Message")
    def message_short(self, obj):
        return obj.message[:120]

    @admin.action(description="Acknowledge selected issues")
    def acknowledge_selected(self, request, queryset):
        updated = queryset.update(status=MemoryIngestionIssue.Status.ACKNOWLEDGED, updated_at=timezone.now())
        self.message_user(request, f"Acknowledged {updated} memory ingestion issue(s).")

    @admin.action(description="Resolve selected issues")
    def resolve_selected(self, request, queryset):
        now = timezone.now()
        updated = queryset.update(status=MemoryIngestionIssue.Status.RESOLVED, resolved_at=now, updated_at=now)
        self.message_user(request, f"Resolved {updated} memory ingestion issue(s).")

    @admin.action(description="Ignore selected issues")
    def ignore_selected(self, request, queryset):
        updated = queryset.update(status=MemoryIngestionIssue.Status.IGNORED, updated_at=timezone.now())
        self.message_user(request, f"Ignored {updated} memory ingestion issue(s).")


@admin.register(MemoryGraphEntity)
class MemoryGraphEntityAdmin(admin.ModelAdmin):
    list_display = ("entity_id", "entity_type", "canonical_name", "is_active", "sensitivity", "updated_at")
    list_filter = ("entity_type", "is_active", "sensitivity")
    search_fields = ("entity_id", "entity_type", "canonical_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MemoryGraphExtractionRun)
class MemoryGraphExtractionRunAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "snapshot", "status", "started_at", "finished_at", "created_at")
    list_filter = ("status", "source__domain", "created_at")
    search_fields = ("source__code", "snapshot__source_object_id", "error_message")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source", "snapshot")


@admin.register(MemoryGraphSchemaProposal)
class MemoryGraphSchemaProposalAdmin(admin.ModelAdmin):
    list_display = ("proposal_kind", "status", "department", "confidence", "reviewed_by", "reviewed_at", "created_at")
    list_filter = ("proposal_kind", "status", "department", "created_at", "reviewed_at")
    search_fields = ("department", "rationale")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("reviewed_by",)


@admin.register(MemoryGraphReviewItem)
class MemoryGraphReviewItemAdmin(admin.ModelAdmin):
    list_display = ("item_kind", "status", "source", "snapshot", "reviewed_by", "reviewed_at", "created_at")
    list_filter = ("item_kind", "status", "source__domain", "created_at")
    search_fields = ("source__code", "snapshot__source_object_id", "decision")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source", "snapshot", "reviewed_by")


@admin.register(MemoryWriteRequest)
class MemoryWriteRequestAdmin(admin.ModelAdmin):
    list_display = ("request_id", "actor", "target_scope", "status", "processed_at", "created_at")
    list_filter = ("target_scope", "status", "created_at", "processed_at")
    search_fields = ("request_id", "actor__username", "error_message")
    readonly_fields = ("request_id", "created_at", "updated_at", "processed_at")
    autocomplete_fields = ("actor", "session")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("actor", "session")


@admin.register(MemoryKnowledgeItem)
class MemoryKnowledgeItemAdmin(admin.ModelAdmin):
    list_display = ("memory_id", "scope", "owner_user", "kind", "status", "sensitivity", "updated_at")
    list_filter = ("scope", "kind", "status", "sensitivity", "created_at", "updated_at")
    search_fields = ("memory_id", "text_hash", "owner_user__username")
    readonly_fields = ("memory_id", "text_hash", "created_at", "updated_at")
    autocomplete_fields = ("owner_user", "source_session", "created_by", "supersedes")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("owner_user", "created_by", "source_session")


@admin.register(MemoryKnowledgeEvent)
class MemoryKnowledgeEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "event_type", "knowledge_item", "actor", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("event_id", "knowledge_item__memory_id", "actor__username")
    readonly_fields = ("event_id", "created_at")
    autocomplete_fields = ("knowledge_item", "actor")


@admin.register(MemoryKnowledgeCandidate)
class MemoryKnowledgeCandidateAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "source_item", "created_by", "reviewer", "reviewed_at", "created_at")
    list_filter = ("status", "created_at", "reviewed_at")
    search_fields = ("source_item__memory_id", "created_by__username", "reviewer__username", "decision")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source_item", "created_by", "reviewer")


@admin.register(MemoryClaim)
class MemoryClaimAdmin(admin.ModelAdmin):
    list_display = ("claim_id", "claim_type", "status", "source", "knowledge_item", "confidence", "sensitivity", "reviewed_at")
    list_filter = ("claim_type", "status", "sensitivity", "source__domain", "reviewed_at", "created_at")
    search_fields = ("claim_id", "text", "source__code", "knowledge_item__memory_id", "evidence_hash")
    readonly_fields = ("claim_id", "evidence_hash", "created_at", "updated_at")
    autocomplete_fields = ("source", "source_chunk", "snapshot", "knowledge_item", "reviewer", "created_by")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("source", "source_chunk", "snapshot", "knowledge_item", "reviewer", "created_by")


@admin.register(MemoryReflectionRun)
class MemoryReflectionRunAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "dry_run", "window_start", "window_end", "started_at", "finished_at")
    list_filter = ("status", "dry_run", "created_at", "started_at")
    search_fields = ("error_message",)
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("created_by",)


@admin.register(SecretHandle)
class SecretHandleAdmin(admin.ModelAdmin):
    list_display = ("handle", "provider", "label", "owner_user", "scope", "status", "created_at")
    list_filter = ("provider", "status", "scope", "created_at")
    search_fields = ("handle", "label", "owner_user__username")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("owner_user", "created_by")


@admin.register(SecretAccessAudit)
class SecretAccessAuditAdmin(admin.ModelAdmin):
    list_display = ("secret_handle", "actor", "action", "decision", "request_id", "created_at")
    list_filter = ("action", "decision", "created_at")
    search_fields = ("secret_handle__handle", "actor__username", "request_id")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("actor", "secret_handle")


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
