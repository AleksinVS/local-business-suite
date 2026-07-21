from django.contrib import admin
from .models import (
    AIWindowContextSnapshot,
    AgentActionLog,
    ChatAttachment,
    ChatMessage,
    ChatSession,
    PendingAction,
    SlashCommand,
)

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("external_id", "user", "channel", "status", "created_at")
    list_filter = ("channel", "status", "created_at")
    search_fields = ("external_id", "title")

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "role", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("content",)

@admin.register(ChatAttachment)
class ChatAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "file_name", "file_type", "file_size", "created_at")
    list_filter = ("file_type", "created_at")
    search_fields = ("file_name",)

@admin.register(PendingAction)
class PendingActionAdmin(admin.ModelAdmin):
    list_display = ("token", "tool_code", "action_kind", "status", "actor", "created_at")
    list_filter = ("action_kind", "status", "created_at")
    search_fields = ("tool_code",)

@admin.register(AgentActionLog)
class AgentActionLogAdmin(admin.ModelAdmin):
    list_display = ("id", "tool_code", "action_kind", "status", "actor", "created_at")
    list_filter = ("action_kind", "status", "created_at")
    search_fields = ("tool_code",)


@admin.register(SlashCommand)
class SlashCommandAdmin(admin.ModelAdmin):
    list_display = ("name", "shortcut", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("name", "shortcut", "description", "user__username")


@admin.register(AIWindowContextSnapshot)
class AIWindowContextSnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "window_id", "context_version", "is_current", "expires_at")
    list_filter = ("is_current", "created_at", "expires_at")
    search_fields = ("window_id", "context_hash", "user__username")
    readonly_fields = ("sanitized_envelope", "resolved_summary", "context_hash", "created_at", "updated_at")
