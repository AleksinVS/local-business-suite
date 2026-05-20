from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models


class User(AbstractUser):
    """
    Расширенная модель пользователя с привязкой к организационной структуре.
    """

    department = models.ForeignKey(
        "core.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="Подразделение",
        help_text="Подразделение пользователя (синхронизируется с AD OU)",
    )

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self):
        return self.get_full_name() or self.username

    def get_department_path(self):
        """Получить полный путь подразделения"""
        if self.department:
            return self.department.full_name
        return "Без подразделения"

    def get_ou_path(self):
        """Получить полный путь OU"""
        return "Без OU"


class ExternalIdentity(models.Model):
    class Provider(models.TextChoices):
        ACTIVE_DIRECTORY = "active_directory", "Active Directory"

    class SyncStatus(models.TextChoices):
        MANUAL = "manual", "Manual"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"
        STALE = "stale", "Stale"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="external_identities")
    provider = models.CharField(
        max_length=64,
        choices=Provider.choices,
        default=Provider.ACTIVE_DIRECTORY,
    )
    subject_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="AD SID/object identifier when available.",
    )
    username = models.CharField(max_length=150, blank=True)
    upn = models.CharField(max_length=255, blank=True)
    distinguished_name = models.CharField(max_length=500, blank=True)
    domain = models.CharField(max_length=120, blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    sync_status = models.CharField(
        max_length=32,
        choices=SyncStatus.choices,
        default=SyncStatus.MANUAL,
    )
    last_synced_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider", "domain", "username", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "subject_id"],
                condition=~models.Q(subject_id=""),
                name="accounts_external_identity_provider_subject_uniq",
            ),
            models.UniqueConstraint(
                fields=["provider", "domain", "username"],
                condition=~models.Q(username=""),
                name="accounts_external_identity_provider_domain_username_uniq",
            ),
            models.UniqueConstraint(
                fields=["user", "provider"],
                name="accounts_external_identity_user_provider_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "domain", "username"]),
            models.Index(fields=["provider", "subject_id"]),
            models.Index(fields=["user", "provider"]),
        ]
        verbose_name = "External identity"
        verbose_name_plural = "External identities"

    def __str__(self):
        return f"{self.provider}:{self.domain}\\{self.username or self.subject_id}"
