from django.contrib import admin

from .models import SettingsChange, SettingsChangeComment, SettingsEnvProposal


@admin.register(SettingsChange)
class SettingsChangeAdmin(admin.ModelAdmin):
    list_display = ("setting_id", "domain", "action", "status", "actor", "created_at", "applied_at")
    list_filter = ("domain", "action", "status", "storage_kind")
    search_fields = ("setting_id", "domain", "actor__username")
    readonly_fields = ("created_at", "applied_at")


@admin.register(SettingsChangeComment)
class SettingsChangeCommentAdmin(admin.ModelAdmin):
    list_display = ("change", "actor", "created_at")
    search_fields = ("change__setting_id", "actor__username")


@admin.register(SettingsEnvProposal)
class SettingsEnvProposalAdmin(admin.ModelAdmin):
    list_display = ("target_label", "status", "actor", "created_at")
    list_filter = ("status",)
    search_fields = ("target_label", "actor__username")
