from django.contrib import admin
from .models import ChatSession, ChatMessage, PendingAction, AgentActionLog, ChatAttachment

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("external_id", "user", "channel", "status", "created_at")
    list_filter = ("channel", "status", "created_at")
    search_fields = ("external_id", "user__username", "title")

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
    search_fields = ("tool_code", "actor__username")

@admin.register(AgentActionLog)
class AgentActionLogAdmin(admin.ModelAdmin):
    list_display = ("id", "tool_code", "action_kind", "status", "actor", "created_at")
    list_filter = ("action_kind", "status", "created_at")
    search_fields = ("tool_code", "actor__username")
