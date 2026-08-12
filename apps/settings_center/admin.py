from django.contrib import admin

from .models import SettingsChange, SettingsChangeComment, SettingsEnvProposal


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
