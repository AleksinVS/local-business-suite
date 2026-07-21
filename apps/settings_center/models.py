from django.conf import settings
from django.db import models
from django.utils import timezone


class SettingsChange(models.Model):
    class Action(models.TextChoices):
        PREVIEW = "preview", "Предпросмотр"
        APPLY = "apply", "Применение"
        USER_CREATE = "user_create", "Создание пользователя"
        USER_UPDATE = "user_update", "Обновление пользователя"
        USER_DISABLE = "user_disable", "Отключение пользователя"
        AD_LINK = "ad_link", "Связь с AD"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        APPLIED = "applied", "Применено"
        REJECTED = "rejected", "Отклонено"
        FAILED = "failed", "Ошибка"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="settings_changes",
        blank=True,
        null=True,
    )
    setting_id = models.CharField(max_length=160)
    domain = models.CharField(max_length=64)
    storage_kind = models.CharField(max_length=64)
    action = models.CharField(max_length=32, choices=Action.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    before_hash = models.CharField(max_length=80, blank=True)
    after_hash = models.CharField(max_length=80, blank=True)
    masked_diff = models.JSONField(default=dict, blank=True)
    validation_result = models.JSONField(default=dict, blank=True)
    requires_restart = models.BooleanField(default=False)
    requires_reindex = models.BooleanField(default=False)
    applied_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["setting_id", "-created_at"]),
            models.Index(fields=["domain", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def mark_applied(self):
        self.status = self.Status.APPLIED
        self.applied_at = timezone.now()
        self.save(update_fields=["status", "applied_at"])

    def __str__(self):
        return f"{self.setting_id}:{self.action}:{self.status}"


class SettingsChangeComment(models.Model):
    change = models.ForeignKey(SettingsChange, on_delete=models.CASCADE, related_name="comments")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="settings_change_comments")
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class SettingsEnvProposal(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        EXPORTED = "exported", "Экспортировано"
        APPLIED_EXTERNALLY = "applied_externally", "Применено вне портала"
        REJECTED = "rejected", "Отклонено"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="settings_env_proposals")
    target_label = models.CharField(max_length=120)
    file_path = models.CharField(max_length=500)
    masked_changes = models.JSONField(default=dict)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return f"{self.target_label}:{self.status}:{self.pk}"
