import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class NotificationSeverity(models.TextChoices):
    INFO = "info", "Обычное"
    WARNING = "warning", "Важное"
    CRITICAL = "critical", "Критичное"


class NotificationEvent(models.Model):
    event_id = models.UUIDField("Идентификатор события", default=uuid.uuid4, unique=True, editable=False)
    event_type = models.CharField("Тип события", max_length=120)
    source_app = models.CharField("Приложение-источник", max_length=64)
    source_object_type = models.CharField("Тип объекта", max_length=80)
    source_object_id = models.CharField("Идентификатор объекта", max_length=120)
    title = models.CharField("Заголовок", max_length=160)
    body = models.CharField("Текст", max_length=240, blank=True)
    target_url = models.CharField("Ссылка", max_length=500)
    severity = models.CharField(
        "Важность",
        max_length=16,
        choices=NotificationSeverity.choices,
        default=NotificationSeverity.INFO,
    )
    metadata = models.JSONField("Метаданные", default=dict, blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["event_type", "-created_at"]),
            models.Index(fields=["source_app", "source_object_type", "source_object_id"]),
            models.Index(fields=["severity", "-created_at"]),
        ]
        verbose_name = "Событие уведомления"
        verbose_name_plural = "События уведомлений"

    def __str__(self):
        return f"{self.event_type}: {self.title}"


class NotificationRecipientState(models.TextChoices):
    NEW = "new", "Новое"
    SEEN = "seen", "Просмотрено"
    READ = "read", "Прочитано"
    DISMISSED = "dismissed", "Скрыто"


class NotificationRecipient(models.Model):
    event = models.ForeignKey(
        NotificationEvent,
        on_delete=models.CASCADE,
        related_name="recipients",
        verbose_name="Событие",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_recipients",
        verbose_name="Получатель",
    )
    state = models.CharField(
        "Состояние",
        max_length=16,
        choices=NotificationRecipientState.choices,
        default=NotificationRecipientState.NEW,
    )
    delivered_at = models.DateTimeField("Доставлено клиенту", blank=True, null=True)
    seen_at = models.DateTimeField("Просмотрено", blank=True, null=True)
    read_at = models.DateTimeField("Прочитано", blank=True, null=True)
    dismissed_at = models.DateTimeField("Скрыто", blank=True, null=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="notifications_event_user_uniq"),
        ]
        indexes = [
            models.Index(fields=["user", "-id"]),
            models.Index(fields=["user", "state", "-id"]),
            models.Index(fields=["state", "-created_at"]),
        ]
        verbose_name = "Получатель уведомления"
        verbose_name_plural = "Получатели уведомлений"

    @property
    def cursor(self):
        return self.pk

    def mark_seen(self):
        if self.state == NotificationRecipientState.NEW:
            self.state = NotificationRecipientState.SEEN
            self.seen_at = timezone.now()
            self.save(update_fields=["state", "seen_at"])

    def mark_read(self):
        if self.state == NotificationRecipientState.DISMISSED:
            return
        self.state = NotificationRecipientState.READ
        now = timezone.now()
        if not self.seen_at:
            self.seen_at = now
        self.read_at = now
        self.save(update_fields=["state", "seen_at", "read_at"])

    def dismiss(self):
        self.state = NotificationRecipientState.DISMISSED
        now = timezone.now()
        if not self.seen_at:
            self.seen_at = now
        if not self.read_at:
            self.read_at = now
        self.dismissed_at = now
        self.save(update_fields=["state", "seen_at", "read_at", "dismissed_at"])


class NotificationChannel(models.TextChoices):
    IN_APP = "in_app", "В портале"
    BROWSER = "browser", "Браузер"
    DESKTOP = "desktop", "Настольное приложение"


class NotificationPreference(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
        verbose_name="Пользователь",
    )
    channel = models.CharField("Канал", max_length=32, choices=NotificationChannel.choices)
    event_type = models.CharField("Тип события", max_length=120, default="*")
    enabled = models.BooleanField("Включено", default=True)
    min_severity = models.CharField(
        "Минимальная важность",
        max_length=16,
        choices=NotificationSeverity.choices,
        default=NotificationSeverity.INFO,
    )
    quiet_hours = models.JSONField("Тихие часы", default=dict, blank=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ["channel", "event_type"]
        constraints = [
            models.UniqueConstraint(fields=["user", "channel", "event_type"], name="notifications_pref_user_channel_event_uniq"),
        ]
        indexes = [
            models.Index(fields=["user", "channel"]),
        ]
        verbose_name = "Настройка уведомлений"
        verbose_name_plural = "Настройки уведомлений"

    def __str__(self):
        return f"{self.user_id}:{self.channel}:{self.event_type}:{self.enabled}"


class BrowserNotificationPermission(models.TextChoices):
    DEFAULT = "default", "Не запрошено"
    GRANTED = "granted", "Разрешено"
    DENIED = "denied", "Запрещено"


class NotificationBrowserClient(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_browser_clients",
        verbose_name="Пользователь",
    )
    browser_fingerprint_hash = models.CharField("Хеш браузера", max_length=96)
    user_agent_family = models.CharField("Браузер", max_length=120, blank=True)
    notification_permission = models.CharField(
        "Разрешение уведомлений",
        max_length=16,
        choices=BrowserNotificationPermission.choices,
        default=BrowserNotificationPermission.DEFAULT,
    )
    enabled = models.BooleanField("Включено на устройстве", default=False)
    last_seen_at = models.DateTimeField("Последняя активность", default=timezone.now)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ["-last_seen_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "browser_fingerprint_hash"], name="notifications_browser_client_user_hash_uniq"),
        ]
        indexes = [
            models.Index(fields=["user", "-last_seen_at"]),
            models.Index(fields=["notification_permission", "-last_seen_at"]),
        ]
        verbose_name = "Браузерный клиент уведомлений"
        verbose_name_plural = "Браузерные клиенты уведомлений"

    def __str__(self):
        return f"{self.user_id}:{self.user_agent_family or 'browser'}"


class NotificationDeviceToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_device_tokens",
        verbose_name="Пользователь",
    )
    device_name = models.CharField("Название устройства", max_length=160)
    platform = models.CharField("Платформа", max_length=64)
    token_hash = models.CharField("Хеш токена", max_length=128, unique=True)
    scopes = models.JSONField("Права", default=list, blank=True)
    last_seen_at = models.DateTimeField("Последняя активность", blank=True, null=True)
    revoked_at = models.DateTimeField("Отозвано", blank=True, null=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "revoked_at"]),
            models.Index(fields=["platform", "-created_at"]),
        ]
        verbose_name = "Токен устройства уведомлений"
        verbose_name_plural = "Токены устройств уведомлений"

    @property
    def is_active(self):
        return self.revoked_at is None

    def __str__(self):
        return f"{self.user_id}:{self.device_name}:{self.platform}"


class NotificationDeviceLinkCode(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_device_link_codes",
        verbose_name="Пользователь",
    )
    code_hash = models.CharField("Хеш кода", max_length=128, unique=True)
    device_name = models.CharField("Название устройства", max_length=160, blank=True)
    platform = models.CharField("Платформа", max_length=64, blank=True)
    expires_at = models.DateTimeField("Истекает")
    used_at = models.DateTimeField("Использовано", blank=True, null=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["expires_at", "used_at"]),
        ]
        verbose_name = "Код подключения устройства"
        verbose_name_plural = "Коды подключения устройств"

    @property
    def is_active(self):
        return self.used_at is None and self.expires_at > timezone.now()

    def __str__(self):
        return f"{self.user_id}:{self.expires_at:%Y-%m-%d %H:%M}"
