import uuid

from django.conf import settings
from django.db import models


class ChatSession(models.Model):
    class Channel(models.TextChoices):
        INTERNAL = "internal", "Internal"
        LIBRECHAT = "librechat", "LibreChat"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ai_chat_sessions")
    title = models.CharField(max_length=255, blank=True)
    channel = models.CharField(max_length=32, choices=Channel.choices, default=Channel.INTERNAL)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    last_message_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        verbose_name = "AI chat session"
        verbose_name_plural = "AI chat sessions"

    def __str__(self):
        return self.title or f"Chat {self.external_id}"


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"
        TOOL = "tool", "Tool"

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    tool_name = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "AI chat message"
        verbose_name_plural = "AI chat messages"


class AgentActionLog(models.Model):
    class ActionKind(models.TextChoices):
        READ = "read", "Read"
        WRITE = "write", "Write"
        ADMIN = "admin", "Admin"

    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        DENIED = "denied", "Denied"
        FAILED = "failed", "Failed"

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="actions",
    )
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="actions",
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ai_actions")
    tool_code = models.CharField(max_length=120)
    action_kind = models.CharField(max_length=16, choices=ActionKind.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "AI action log"
        verbose_name_plural = "AI action logs"
