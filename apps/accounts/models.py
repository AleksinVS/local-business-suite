import uuid

from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models


class User(AbstractUser):
    """
    Расширенная модель пользователя с привязкой к организационной структуре.
    """

    department = models.ForeignKey(
        "core.Department",
        on_delete=models.PROTECT,
        related_name="users",
        verbose_name="Подразделение",
        help_text="Обязательное подразделение пользователя (синхронизируется с AD OU)",
    )

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self):
        return self.get_full_name() or self.username

    def save(self, *args, **kwargs):
        if self.department_id is None:
            from .department_policy import get_unassigned_user_department

            self.department = get_unassigned_user_department()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"department"}
        return super().save(*args, **kwargs)

    @property
    def requires_department_assignment(self):
        from .department_policy import is_unassigned_user_department

        return is_unassigned_user_department(self.department)

    def get_department_path(self):
        """Получить полный путь подразделения"""
        if self.department:
            return self.department.full_name
        return "Без подразделения"

    def get_ou_path(self):
        """Получить полный путь OU"""
        return "Без OU"


class GroupProfile(models.Model):
    """Понятное описание группы доступа для нетехнических пользователей.

    Стандартная группа Django хранит только техническое имя (например,
    ``doctor``). Профиль добавляет человекочитаемое название и комментарий:
    кому выдавать группу и что она даёт. Для предопределённых групп профиль
    синхронизируется командой ``seed_roles`` из контракта ролей.
    """

    group = models.OneToOneField(
        Group,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="Группа",
    )
    title = models.CharField(
        "Название",
        max_length=150,
        blank=True,
        help_text="Понятное название группы, например «Врач».",
    )
    description = models.TextField(
        "Комментарий",
        blank=True,
        help_text="Кому выдавать группу и какие возможности она даёт.",
    )
    is_predefined = models.BooleanField(
        "Предопределённая",
        default=False,
        help_text="Создана автоматически из контракта ролей; название и комментарий обновляются командой seed_roles.",
    )
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Описание группы"
        verbose_name_plural = "Описания групп"

    def __str__(self):
        return self.title or self.group.name


class AccessAssignmentAudit(models.Model):
    """Журнал атомарного изменения ролей и технических флагов доступа."""

    class Source(models.TextChoices):
        SETTINGS_CENTER = "settings_center", "Раздел доступа"
        DJANGO_ADMIN_BREAK_GLASS = "django_admin_break_glass", "Резервный Django Admin"
        AI = "ai", "ИИ-инструмент"
        AD_SYNC = "ad_sync", "Синхронизация Active Directory"

    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="access_assignment_actions",
        verbose_name="Кто изменил",
    )
    target_user = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="access_assignment_history",
        verbose_name="Чей доступ изменён",
    )
    roles_before = models.JSONField("Роли до изменения", default=list)
    roles_after = models.JSONField("Роли после изменения", default=list)
    roles_added = models.JSONField("Добавленные роли", default=list)
    roles_removed = models.JSONField("Удалённые роли", default=list)
    flags_before = models.JSONField("Технические флаги до изменения", default=dict)
    flags_after = models.JSONField("Технические флаги после изменения", default=dict)
    flags_changed = models.JSONField("Изменённые технические флаги", default=list)
    risk_markers = models.JSONField("Маркеры риска", default=list)
    risk_confirmed = models.BooleanField("Риск подтверждён", default=False)
    source = models.CharField(
        "Источник изменения",
        max_length=48,
        choices=Source.choices,
        default=Source.SETTINGS_CENTER,
        db_index=True,
    )
    is_break_glass = models.BooleanField("Резервное изменение", default=False)
    reason = models.TextField("Причина", blank=True)
    correlation_id = models.UUIDField("Идентификатор операции", default=uuid.uuid4, editable=False)
    preview_fingerprint = models.CharField(
        "Отпечаток предпросмотра",
        max_length=64,
        unique=True,
        null=True,
        editable=False,
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["actor", "-created_at"], name="accounts_ac_actor_i_40b502_idx"),
            models.Index(fields=["target_user", "-created_at"], name="accounts_ac_target__cd1db8_idx"),
        ]
        verbose_name = "Изменение доступа"
        verbose_name_plural = "Изменения доступа"

    def __str__(self):
        return f"Изменение доступа #{self.pk}"


class ExternalIdentity(models.Model):
    class Provider(models.TextChoices):
        ACTIVE_DIRECTORY = "active_directory", "Active Directory"

    class SyncStatus(models.TextChoices):
        MANUAL = "manual", "Вручную"
        VERIFIED = "verified", "Проверено"
        FAILED = "failed", "Ошибка"
        STALE = "stale", "Устарело"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="external_identities", verbose_name="Пользователь")
    provider = models.CharField(
        "Поставщик",
        max_length=64,
        choices=Provider.choices,
        default=Provider.ACTIVE_DIRECTORY,
    )
    subject_id = models.CharField(
        "Идентификатор субъекта",
        max_length=255,
        blank=True,
        help_text="AD SID или идентификатор объекта, если доступен.",
    )
    username = models.CharField("Логин", max_length=150, blank=True)
    upn = models.CharField("UPN", max_length=255, blank=True)
    distinguished_name = models.CharField("Distinguished name", max_length=500, blank=True)
    domain = models.CharField("Домен", max_length=120, blank=True)
    attributes = models.JSONField("Атрибуты", default=dict, blank=True)
    sync_status = models.CharField(
        "Статус синхронизации",
        max_length=32,
        choices=SyncStatus.choices,
        default=SyncStatus.MANUAL,
    )
    last_synced_at = models.DateTimeField("Последняя синхронизация", blank=True, null=True)
    last_error = models.TextField("Последняя ошибка", blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

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
        verbose_name = "Внешняя учетная запись"
        verbose_name_plural = "Внешние учетные записи"

    def __str__(self):
        return f"{self.provider}:{self.domain}\\{self.username or self.subject_id}"
