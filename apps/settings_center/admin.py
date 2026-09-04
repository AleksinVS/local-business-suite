from django.contrib import admin

from .models import (
    RuntimeSettingDocument,
    SettingsChange,
    SettingsChangeComment,
    SettingsEnvProposal,
)


@admin.register(RuntimeSettingDocument)
class RuntimeSettingDocumentAdmin(admin.ModelAdmin):
    """Только просмотр: рабочие документы меняются через проверяемые сервисы."""

    list_display = (
        "document_id",
        "schema_version",
        "revision",
        "updated_by",
        "updated_at",
    )
    search_fields = ("document_id", "updated_by__username")
    readonly_fields = (
        "document_id",
        "schema_version",
        "payload",
        "revision",
        "content_hash",
        "default_hash",
        "updated_by",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SettingsChange)
class SettingsChangeAdmin(admin.ModelAdmin):
    list_display = ("setting_id", "domain", "action", "status", "actor", "created_at", "applied_at")
    list_filter = ("domain", "action", "status", "storage_kind")
    search_fields = ("setting_id", "domain", "actor__username")
    readonly_fields = (
        "actor",
        "setting_id",
        "domain",
        "storage_kind",
        "action",
        "status",
        "before_hash",
        "after_hash",
        "contract_relpath",
        "masked_diff",
        "validation_result",
        "operation_fingerprint",
        "document_revision_before",
        "document_revision_after",
        "failure_code",
        "requires_restart",
        "requires_reindex",
        "file_written_at",
        "reconciled_at",
        "rollback_of",
        "created_at",
        "applied_at",
    )
    exclude = ("before_snapshot", "after_snapshot")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SettingsChangeComment)
class SettingsChangeCommentAdmin(admin.ModelAdmin):
    list_display = ("change", "actor", "created_at")
    search_fields = ("change__setting_id", "actor__username")


@admin.register(SettingsEnvProposal)
class SettingsEnvProposalAdmin(admin.ModelAdmin):
    list_display = ("target_label", "status", "actor", "created_at")
    list_filter = ("status",)
    search_fields = ("target_label", "actor__username")
