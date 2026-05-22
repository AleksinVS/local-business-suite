import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def default_pending_action_expires_at():
    ttl_seconds = getattr(settings, "LOCAL_BUSINESS_AI_PENDING_ACTION_TTL_SECONDS", 900)
    return timezone.now() + timezone.timedelta(seconds=ttl_seconds)


class SlashCommand(models.Model):
    """User-created custom slash command (prompt template)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="slash_commands",
        db_constraint=False,
    )
    name = models.CharField(
        max_length=64,
        help_text="Command name without the leading slash, e.g. 'summary'",
    )
    shortcut = models.CharField(
        max_length=16,
        blank=True,
        help_text="Optional short alias, e.g. 'sum'",
    )
    description = models.CharField(max_length=255, blank=True)
    template = models.TextField(
        help_text="Prompt template. Use {input} as placeholder for user text after the command.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="unique_slash_command_name_per_user",
            ),
        ]
        ordering = ["name"]
        verbose_name = "Слэш-команда"
        verbose_name_plural = "Слэш-команды"

    def __str__(self):
        return f"/{self.name}"


class ChatSession(models.Model):
    class Channel(models.TextChoices):
        INTERNAL = "internal", "Internal"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_chat_sessions",
        db_constraint=False,
    )
    title = models.CharField(max_length=255, blank=True)
    channel = models.CharField(max_length=32, choices=Channel.choices, default=Channel.INTERNAL)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    last_message_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["-updated_at", "-id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["channel"]),
            models.Index(fields=["last_message_at"]),
        ]
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
        indexes = [
            models.Index(fields=["created_at", "id"]),
            models.Index(fields=["role"]),
        ]
        verbose_name = "AI chat message"
        verbose_name_plural = "AI chat messages"


class PendingAction(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tool_code = models.CharField(max_length=120)
    action_kind = models.CharField(max_length=16)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_pending_actions",
        db_constraint=False,
    )
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="pending_actions",
    )
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField(default=default_pending_action_expires_at)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["-created_at", "-id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["tool_code"]),
            models.Index(fields=["expires_at"], name="ai_pendinga_expires_77ce4c_idx"),
        ]
        verbose_name = "AI pending action"
        verbose_name_plural = "AI pending actions"

    def __str__(self):
        return f"Pending {self.tool_code} ({self.token})"


class AgentActionLog(models.Model):
    class ActionKind(models.TextChoices):
        READ = "read", "Read"
        WRITE = "write", "Write"
        ADMIN = "admin", "Admin"

    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        DENIED = "denied", "Denied"
        FAILED = "failed", "Failed"
        PENDING = "pending", "Pending"

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
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ai_actions",
        db_constraint=False,
    )
    tool_code = models.CharField(max_length=120)
    action_kind = models.CharField(max_length=16, choices=ActionKind.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["-created_at", "-id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["action_kind"]),
            models.Index(fields=["tool_code"]),
        ]
        verbose_name = "AI action log"
        verbose_name_plural = "AI action logs"


class ChatAttachment(models.Model):
    class FileType(models.TextChoices):
        IMAGE = "image", "Image"
        DOCUMENT = "document", "Document"
        AUDIO = "audio", "Audio"
        OTHER = "other", "Other"

    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="attachments",
        blank=True,
        null=True,
    )
    file = models.FileField(upload_to="chat_attachments/%Y/%m/%d/")
    file_type = models.CharField(max_length=32, choices=FileType.choices, default=FileType.OTHER)
    file_name = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(help_text="File size in bytes", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["file_type"]),
        ]
        verbose_name = "Chat attachment"
        verbose_name_plural = "Chat attachments"

    def __str__(self):
        return f"{self.file_name} ({self.get_file_type_display()})"
