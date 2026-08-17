from django.contrib import admin

from .models import (
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
)


class ActiveSuperuserReserveAdmin(admin.ModelAdmin):
    """Django Admin is a reserve path, never a staff authority."""

    def _active_superuser(self, request):
        return bool(getattr(request.user, "is_active", False) and getattr(request.user, "is_superuser", False))

    def has_add_permission(self, request):
        return self._active_superuser(request)

    def has_change_permission(self, request, obj=None):
        return self._active_superuser(request)

    def has_delete_permission(self, request, obj=None):
        return self._active_superuser(request)


class ReadOnlyOperationalAdmin(admin.ModelAdmin):
    """Audit and operational state is written only by domain services/workers."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MemoryFileObject)
class MemoryFileObjectAdmin(ActiveSuperuserReserveAdmin):
    list_display = ("file_id", "source", "lifecycle_status", "current_version", "last_seen_at", "updated_at")
    list_filter = ("lifecycle_status", "source__domain", "source__source_kind", "updated_at")
    search_fields = ("file_id", "source__code")
    readonly_fields = ("file_id", "first_seen_at", "created_at", "updated_at")
    autocomplete_fields = ("source", "current_version", "current_physical_placement")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("source", "current_version", "current_physical_placement")


@admin.register(MemoryFileObjectVersion)
class MemoryFileObjectVersionAdmin(ActiveSuperuserReserveAdmin):
    list_display = ("file_object", "short_sha256", "size_bytes", "storage_backend", "version_status", "created_at")
    list_filter = ("storage_backend", "version_status", "created_at")
    search_fields = ("file_object__file_id", "sha256", "source_object__object_id")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("file_object", "source_object")

    @admin.display(ordering="sha256", description="SHA-256")
    def short_sha256(self, obj):
        return (obj.sha256 or "")[:12]


@admin.register(MemoryFilePhysicalPlacement)
class MemoryFilePhysicalPlacementAdmin(ReadOnlyOperationalAdmin):
    list_display = ("file_object", "storage_backend", "path_role", "placement_status", "is_current", "updated_at")
    list_filter = ("storage_backend", "path_role", "placement_status", "is_current", "updated_at")
    search_fields = ("file_object__file_id", "relative_path", "source_object__object_id")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("file_object", "source_object")


@admin.register(MemoryFilePathAlias)
class MemoryFilePathAliasAdmin(ActiveSuperuserReserveAdmin):
    list_display = ("source", "relative_path", "file_object", "alias_kind", "is_active", "last_seen_at")
    list_filter = ("alias_kind", "is_active", "source__domain")
    search_fields = ("source__code", "relative_path", "file_object__file_id")
    autocomplete_fields = ("file_object", "source")


@admin.register(MemoryFileVirtualView)
class MemoryFileVirtualViewAdmin(ActiveSuperuserReserveAdmin):
    list_display = ("source", "slug", "view_kind", "status", "owner_user", "is_system", "updated_at")
    list_filter = ("view_kind", "status", "is_system", "source__domain")
    search_fields = ("source__code", "slug", "title")
    readonly_fields = ("created_at", "updated_at", "generated_at")
    autocomplete_fields = ("source", "owner_user")


@admin.register(MemoryFileVirtualRule)
class MemoryFileVirtualRuleAdmin(ActiveSuperuserReserveAdmin):
    list_display = ("title", "view", "rule_kind", "status", "confidence", "updated_at")
    list_filter = ("rule_kind", "status", "view__view_kind")
    search_fields = ("title", "view__slug")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("view",)


@admin.register(MemoryFileVirtualPlacement)
class MemoryFileVirtualPlacementAdmin(ReadOnlyOperationalAdmin):
    list_display = ("view", "virtual_path", "file_object", "status", "confidence", "review_required")
    list_filter = ("status", "review_required", "placement_source", "view__view_kind")
    search_fields = ("view__slug", "virtual_path", "file_object__file_id")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("view", "file_object", "rule", "created_by")


@admin.register(MemoryFileUsageEvent)
class MemoryFileUsageEventAdmin(ReadOnlyOperationalAdmin):
    list_display = ("event_kind", "source", "safe_path_bucket", "actor", "created_at")
    list_filter = ("event_kind", "source__domain", "created_at")
    search_fields = ("source__code", "safe_path_hash", "safe_path_bucket", "file_object__file_id")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("source", "file_object", "view", "actor")


@admin.register(MemoryFileOrganizationProposal)
class MemoryFileOrganizationProposalAdmin(ReadOnlyOperationalAdmin):
    list_display = ("title", "source", "status", "affected_file_count", "confidence", "reviewed_by", "updated_at")
    list_filter = ("status", "source__domain", "reviewed_at", "created_at")
    search_fields = ("title", "source__code", "proposal_id")
    readonly_fields = ("proposal_id", "created_at", "updated_at")
    autocomplete_fields = ("source", "target_view", "reviewed_by")


@admin.register(MemoryFileOrganizationDecision)
class MemoryFileOrganizationDecisionAdmin(ReadOnlyOperationalAdmin):
    list_display = ("proposal", "decision", "actor", "created_at")
    list_filter = ("decision", "created_at")
    search_fields = ("proposal__title", "comment")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("proposal", "actor")


@admin.register(MemoryFileMoveJob)
class MemoryFileMoveJobAdmin(ReadOnlyOperationalAdmin):
    list_display = ("idempotency_key", "source", "file_object", "status", "target_storage_backend", "retention_until", "updated_at")
    list_filter = ("status", "target_storage_backend", "source__domain", "retention_until")
    search_fields = ("idempotency_key", "file_object__file_id", "expected_sha256")
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at")
    autocomplete_fields = ("source", "file_object", "proposal", "source_placement", "approved_by")
