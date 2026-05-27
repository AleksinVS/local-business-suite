from django.contrib import admin
from django.db.models import Count
from django.utils import timezone

from .models import (
    MemoryAccessAudit,
    MemoryEvalCase,
    MemoryGraphEntity,
    MemoryGraphExtractionRun,
    MemoryGraphReviewItem,
    MemoryGraphSchemaProposal,
    MemoryIngestionIssue,
    MemoryIngestionRun,
    MemoryIndexJob,
    MemoryKnowledgeCandidate,
    MemoryKnowledgeEvent,
    MemoryKnowledgeItem,
    MemoryReflectionRun,
    MemoryReviewAction,
    MemorySearchDocument,
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
        "search_document_count",
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
                _search_document_count=Count("source_objects__search_documents", distinct=True),
                _job_count=Count("index_jobs", distinct=True),
            )
        )

    @admin.display(ordering="_search_document_count", description="Search docs")
    def search_document_count(self, obj):
        return obj._search_document_count

    @admin.display(ordering="_job_count", description="Jobs")
    def job_count(self, obj):
        return obj._job_count


@admin.register(MemorySearchDocument)
class MemorySearchDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "document_id",
        "corpus_type",
        "object_kind",
        "target_display",
        "index_status",
        "indexed_at",
    )
    list_filter = ("corpus_type", "object_kind", "index_status")
    search_fields = ("document_id", "knowledge_item__memory_id", "source_object__object_id", "body_hash")
    readonly_fields = ("created_at", "updated_at", "indexed_at")
    autocomplete_fields = ("source_object", "knowledge_item")
    fieldsets = (
        (None, {"fields": ("document_id", "corpus_type", "object_kind", "knowledge_item", "source_object")}),
        ("Index", {"fields": ("body_hash", "index_status", "indexed_at")}),
        ("Metadata", {"fields": ("metadata", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("source_object", "knowledge_item")

    @admin.display(description="Target")
    def target_display(self, obj):
        if obj.knowledge_item_id:
            return obj.knowledge_item.memory_id
        if obj.source_object_id:
            return obj.source_object.object_id
        return ""


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
        return super().get_queryset(request).select_related("source").annotate(_issue_count=Count("issues"))

    @admin.display(ordering="_issue_count", description="Issues")
    def issue_count(self, obj):
        return obj._issue_count


@admin.register(MemoryIngestionIssue)
class MemoryIngestionIssueAdmin(admin.ModelAdmin):
    list_display = (
        "issue_kind",
        "status",
        "severity",
        "source",
        "source_object_display",
        "assigned_to",
        "message_short",
        "created_at",
    )
    list_filter = ("issue_kind", "status", "severity", "source__domain", "assigned_to", "created_at")
    search_fields = ("source__code", "source_object__relative_path", "message")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source", "source_object", "run", "assigned_to", "reviewed_by")
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


@admin.register(MemoryReviewAction)
class MemoryReviewActionAdmin(admin.ModelAdmin):
    list_display = ("id", "action", "decision", "actor", "issue", "search_document", "source_object", "created_at")
    list_filter = ("action", "decision", "created_at")
    search_fields = (
        "issue__message",
        "search_document__document_id",
        "source_object__relative_path",
        "index_job__request_id",
        "comment",
    )
    readonly_fields = (
        "actor",
        "action",
        "decision",
        "issue",
        "search_document",
        "source_object",
        "index_job",
        "access_audit",
        "before_state",
        "after_state",
        "safe_metadata",
        "comment",
        "created_at",
    )
    autocomplete_fields = ("actor", "issue", "search_document", "source_object", "index_job", "access_audit")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MemoryGraphEntity)
class MemoryGraphEntityAdmin(admin.ModelAdmin):
    list_display = ("entity_id", "entity_type", "canonical_name", "is_active", "sensitivity", "updated_at")
    list_filter = ("entity_type", "is_active", "sensitivity")
    search_fields = ("entity_id", "entity_type", "canonical_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MemoryGraphExtractionRun)
class MemoryGraphExtractionRunAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "status", "started_at", "finished_at", "created_at")
    list_filter = ("status", "source__domain", "created_at")
    search_fields = ("source__code", "error_message")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source",)


@admin.register(MemoryGraphSchemaProposal)
class MemoryGraphSchemaProposalAdmin(admin.ModelAdmin):
    list_display = ("proposal_kind", "status", "department", "confidence", "reviewed_by", "reviewed_at", "created_at")
    list_filter = ("proposal_kind", "status", "department", "created_at", "reviewed_at")
    search_fields = ("department", "rationale")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("reviewed_by",)


@admin.register(MemoryGraphReviewItem)
class MemoryGraphReviewItemAdmin(admin.ModelAdmin):
    list_display = ("item_kind", "status", "source", "reviewed_by", "reviewed_at", "created_at")
    list_filter = ("item_kind", "status", "source__domain", "created_at")
    search_fields = ("source__code", "decision")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source", "reviewed_by")


@admin.register(MemoryWriteRequest)
class MemoryWriteRequestAdmin(admin.ModelAdmin):
    list_display = ("request_id", "actor", "target_scope", "status", "processed_at", "created_at")
    list_filter = ("target_scope", "status", "created_at", "processed_at")
    search_fields = ("request_id", "error_message")
    readonly_fields = ("request_id", "created_at", "updated_at", "processed_at")
    autocomplete_fields = ("actor", "session")

    def get_queryset(self, request):
        return super().get_queryset(request)


@admin.register(MemoryKnowledgeItem)
class MemoryKnowledgeItemAdmin(admin.ModelAdmin):
    list_display = ("memory_id", "scope", "owner_user", "kind", "status", "sensitivity", "updated_at")
    list_filter = ("scope", "kind", "status", "sensitivity", "created_at", "updated_at")
    search_fields = ("memory_id", "text_hash", "knowledge_file_path")
    readonly_fields = ("memory_id", "text_hash", "created_at", "updated_at")
    autocomplete_fields = ("owner_user", "source_session", "created_by", "supersedes")

    def get_queryset(self, request):
        return super().get_queryset(request)


@admin.register(MemoryKnowledgeEvent)
class MemoryKnowledgeEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "event_type", "knowledge_item", "actor", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("event_id", "knowledge_item__memory_id")
    readonly_fields = ("event_id", "created_at")
    autocomplete_fields = ("knowledge_item", "actor")


@admin.register(MemoryKnowledgeCandidate)
class MemoryKnowledgeCandidateAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "source_item", "created_by", "reviewer", "reviewed_at", "created_at")
    list_filter = ("status", "created_at", "reviewed_at")
    search_fields = ("source_item__memory_id", "decision")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source_item", "created_by", "reviewer")


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
    search_fields = ("handle", "label")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("owner_user", "created_by")


@admin.register(SecretAccessAudit)
class SecretAccessAuditAdmin(admin.ModelAdmin):
    list_display = ("secret_handle", "actor", "action", "decision", "request_id", "created_at")
    list_filter = ("action", "decision", "created_at")
    search_fields = ("secret_handle__handle", "request_id")
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
        return super().get_queryset(request).select_related("source")

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
        "returned_documents_count",
        "returned_facts_count",
        "denied_reason_short",
        "created_at",
    )
    list_filter = ("policy_decision", "tool_name", "created_at")
    search_fields = ("request_id", "query_hash")
    readonly_fields = (
        "actor",
        "request_id",
        "query_hash",
        "tool_name",
        "allowed_scope_tokens",
        "returned_document_ids",
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
            {"fields": ("returned_document_ids", "returned_fact_ids", "allowed_scope_tokens", "retrieval_trace")},
        ),
        ("Denied access", {"fields": ("denied_reason",)}),
        ("Timestamps", {"fields": ("created_at",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request)

    def has_add_permission(self, request):
        return False

    @admin.display(description="Documents")
    def returned_documents_count(self, obj):
        return len(obj.returned_document_ids or [])

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
