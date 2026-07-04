from django.contrib import admin
from django.db.models import Count
from django.utils import timezone

from .models import (
    MemoryAccessAudit,
    MemoryEvalCase,
    MemoryExternalConnectorJob,
    MemoryFileMoveJob,
    MemoryFileObject,
    MemoryFileObjectVersion,
    MemoryFileOrganizationDecision,
    MemoryFileOrganizationProposal,
    MemoryFilePathAlias,
    MemoryFilePhysicalPlacement,
    MemoryFileUsageEvent,
    MemoryFileVirtualPlacement,
    MemoryFileVirtualRule,
    MemoryFileVirtualView,
    MemoryGraphEntity,
    MemoryGraphExtractionRun,
    MemoryGraphReviewItem,
    MemoryGraphSchemaProposal,
    MemoryIngestionIssue,
    MemoryIngestionRun,
    MemoryFullTextIndex,
    MemoryKnowledgeItem,
    MemorySearchDocument,
    MemorySource,
    MemorySourceObject,
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
            )
        )

    @admin.display(ordering="_search_document_count", description="Поисковые документы")
    def search_document_count(self, obj):
        return obj._search_document_count


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
        ("Индекс", {"fields": ("body_hash", "index_status", "indexed_at")}),
        ("Метаданные", {"fields": ("metadata", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("source_object", "knowledge_item")

    @admin.display(description="Цель")
    def target_display(self, obj):
        if obj.knowledge_item_id:
            return obj.knowledge_item.memory_id
        if obj.source_object_id:
            return obj.source_object.object_id
        return ""


@admin.register(MemoryFullTextIndex)
class MemoryFullTextIndexAdmin(admin.ModelAdmin):
    list_display = ("document_id", "sensitivity", "is_active", "backend_schema_version", "indexed_at")
    list_filter = ("is_active", "sensitivity", "backend_schema_version")
    search_fields = ("document_id", "search_text")
    readonly_fields = ("created_at", "updated_at", "indexed_at")


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

    @admin.display(ordering="content_hash", description="Хэш содержимого")
    def short_content_hash(self, obj):
        return (obj.content_hash or "")[:12]


@admin.register(MemoryFileObject)
class MemoryFileObjectAdmin(admin.ModelAdmin):
    list_display = ("file_id", "source", "lifecycle_status", "current_version", "last_seen_at", "updated_at")
    list_filter = ("lifecycle_status", "source__domain", "source__source_kind", "updated_at")
    search_fields = ("file_id", "source__code")
    readonly_fields = ("file_id", "first_seen_at", "created_at", "updated_at")
    autocomplete_fields = ("source", "current_version", "current_physical_placement")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("source", "current_version", "current_physical_placement")


@admin.register(MemoryFileObjectVersion)
class MemoryFileObjectVersionAdmin(admin.ModelAdmin):
    list_display = ("file_object", "short_sha256", "size_bytes", "storage_backend", "version_status", "created_at")
    list_filter = ("storage_backend", "version_status", "created_at")
    search_fields = ("file_object__file_id", "sha256", "source_object__object_id")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("file_object", "source_object")

    @admin.display(ordering="sha256", description="SHA-256")
    def short_sha256(self, obj):
        return (obj.sha256 or "")[:12]


@admin.register(MemoryFilePhysicalPlacement)
class MemoryFilePhysicalPlacementAdmin(admin.ModelAdmin):
    list_display = ("file_object", "storage_backend", "path_role", "placement_status", "is_current", "updated_at")
    list_filter = ("storage_backend", "path_role", "placement_status", "is_current", "updated_at")
    search_fields = ("file_object__file_id", "relative_path", "source_object__object_id")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("file_object", "source_object")


@admin.register(MemoryFilePathAlias)
class MemoryFilePathAliasAdmin(admin.ModelAdmin):
    list_display = ("source", "relative_path", "file_object", "alias_kind", "is_active", "last_seen_at")
    list_filter = ("alias_kind", "is_active", "source__domain")
    search_fields = ("source__code", "relative_path", "file_object__file_id")
    autocomplete_fields = ("file_object", "source")


@admin.register(MemoryFileVirtualView)
class MemoryFileVirtualViewAdmin(admin.ModelAdmin):
    list_display = ("source", "slug", "view_kind", "status", "owner_user", "is_system", "updated_at")
    list_filter = ("view_kind", "status", "is_system", "source__domain")
    search_fields = ("source__code", "slug", "title")
    readonly_fields = ("created_at", "updated_at", "generated_at")
    autocomplete_fields = ("source", "owner_user")


@admin.register(MemoryFileVirtualRule)
class MemoryFileVirtualRuleAdmin(admin.ModelAdmin):
    list_display = ("title", "view", "rule_kind", "status", "confidence", "updated_at")
    list_filter = ("rule_kind", "status", "view__view_kind")
    search_fields = ("title", "view__slug")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("view",)


@admin.register(MemoryFileVirtualPlacement)
class MemoryFileVirtualPlacementAdmin(admin.ModelAdmin):
    list_display = ("view", "virtual_path", "file_object", "status", "confidence", "review_required")
    list_filter = ("status", "review_required", "placement_source", "view__view_kind")
    search_fields = ("view__slug", "virtual_path", "file_object__file_id")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("view", "file_object", "rule", "created_by")


@admin.register(MemoryFileUsageEvent)
class MemoryFileUsageEventAdmin(admin.ModelAdmin):
    list_display = ("event_kind", "source", "safe_path_bucket", "actor", "created_at")
    list_filter = ("event_kind", "source__domain", "created_at")
    search_fields = ("source__code", "safe_path_hash", "safe_path_bucket", "file_object__file_id")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("source", "file_object", "view", "actor")


@admin.register(MemoryFileOrganizationProposal)
class MemoryFileOrganizationProposalAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "status", "affected_file_count", "confidence", "reviewed_by", "updated_at")
    list_filter = ("status", "source__domain", "reviewed_at", "created_at")
    search_fields = ("title", "source__code", "proposal_id")
    readonly_fields = ("proposal_id", "created_at", "updated_at")
    autocomplete_fields = ("source", "target_view", "reviewed_by")


@admin.register(MemoryFileOrganizationDecision)
class MemoryFileOrganizationDecisionAdmin(admin.ModelAdmin):
    list_display = ("proposal", "decision", "actor", "created_at")
    list_filter = ("decision", "created_at")
    search_fields = ("proposal__title", "comment")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("proposal", "actor")


@admin.register(MemoryFileMoveJob)
class MemoryFileMoveJobAdmin(admin.ModelAdmin):
    list_display = ("idempotency_key", "source", "file_object", "status", "target_storage_backend", "retention_until", "updated_at")
    list_filter = ("status", "target_storage_backend", "source__domain", "retention_until")
    search_fields = ("idempotency_key", "file_object__file_id", "expected_sha256")
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at")
    autocomplete_fields = ("source", "file_object", "proposal", "source_placement", "approved_by")


@admin.register(MemoryIngestionRun)
class MemoryIngestionRunAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "status", "dry_run", "started_at", "finished_at", "issue_count", "created_at")
    list_filter = ("status", "dry_run", "source__domain", "created_at", "started_at")
    search_fields = ("source__code", "error_message")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("source", "created_by")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("source").annotate(_issue_count=Count("issues"))

    @admin.display(ordering="_issue_count", description="Проблемы")
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

    @admin.display(description="Объект")
    def source_object_display(self, obj):
        return obj.source_object.relative_path if obj.source_object_id else ""

    @admin.display(description="Сообщение")
    def message_short(self, obj):
        return obj.message[:120]

    @admin.action(description="Взять выбранные проблемы в работу")
    def acknowledge_selected(self, request, queryset):
        updated = queryset.update(status=MemoryIngestionIssue.Status.ACKNOWLEDGED, updated_at=timezone.now())
        self.message_user(request, f"Взято в работу проблем памяти: {updated}.")

    @admin.action(description="Закрыть выбранные проблемы")
    def resolve_selected(self, request, queryset):
        now = timezone.now()
        updated = queryset.update(status=MemoryIngestionIssue.Status.RESOLVED, resolved_at=now, updated_at=now)
        self.message_user(request, f"Закрыто проблем памяти: {updated}.")

    @admin.action(description="Игнорировать выбранные проблемы")
    def ignore_selected(self, request, queryset):
        updated = queryset.update(status=MemoryIngestionIssue.Status.IGNORED, updated_at=timezone.now())
        self.message_user(request, f"Проигнорировано проблем памяти: {updated}.")


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


@admin.register(MemoryKnowledgeItem)
class MemoryKnowledgeItemAdmin(admin.ModelAdmin):
    list_display = ("memory_id", "scope", "owner_user", "kind", "status", "sensitivity", "updated_at")
    list_filter = ("scope", "kind", "status", "sensitivity", "created_at", "updated_at")
    search_fields = ("memory_id", "text_hash", "knowledge_file_path")
    readonly_fields = ("memory_id", "text_hash", "created_at", "updated_at")
    autocomplete_fields = ("owner_user", "source_session", "created_by", "supersedes")

    def get_queryset(self, request):
        return super().get_queryset(request)


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


@admin.register(MemoryExternalConnectorJob)
class MemoryExternalConnectorJobAdmin(admin.ModelAdmin):
    list_display = (
        "job_id",
        "source_code",
        "job_kind",
        "status",
        "priority",
        "attempts_display",
        "locked_by",
        "request_id",
        "updated_at",
    )
    list_filter = ("status", "source_code", "job_kind", "created_at", "updated_at")
    search_fields = ("job_id", "source_code", "idempotency_key", "request_id", "error_message", "locked_by")
    readonly_fields = ("job_id", "created_at", "updated_at")
    actions = ("cancel_selected_jobs",)

    @admin.display(description="Попытки")
    def attempts_display(self, obj):
        return f"{obj.attempt_count}/{obj.max_attempts}"

    @admin.action(description="Отменить выбранные ожидающие задания")
    def cancel_selected_jobs(self, request, queryset):
        now = timezone.now()
        updated = queryset.filter(status__in=["pending", "retry_wait"]).update(
            status="cancelled",
            finished_at=now,
            locked_until=None,
            updated_at=now,
        )
        self.message_user(request, f"Отменено заданий очереди памяти: {updated}.")


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
            "Поиск",
            {"fields": ("returned_document_ids", "returned_fact_ids", "allowed_scope_tokens", "retrieval_trace")},
        ),
        ("Отказ доступа", {"fields": ("denied_reason",)}),
        ("Время", {"fields": ("created_at",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request)

    def has_add_permission(self, request):
        return False

    @admin.display(description="Документы")
    def returned_documents_count(self, obj):
        return len(obj.returned_document_ids or [])

    @admin.display(description="Факты")
    def returned_facts_count(self, obj):
        return len(obj.returned_fact_ids or [])

    @admin.display(description="Причина отказа")
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
