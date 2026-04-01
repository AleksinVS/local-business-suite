import uuid

from django.conf import settings
from django.db import models


class WaitingListStatus(models.TextChoices):
    WAITING = "waiting", "В очереди"
    SCHEDULED = "scheduled", "Назначена"
    CONFIRMED = "confirmed", "Подтверждена"
    CANCELLED = "cancelled", "Отменена"


# Bounded service catalog as choices - not a separate relational model
SERVICE_CHOICES = [
    ("s1", "КТ головного мозга"),
    ("s2", "МРТ позвоночника"),
    ("s3", "Рентген грудной клетки"),
]


class WaitingListEntry(models.Model):
    """
    Waiting list entry with int primary key (not UUID).
    Uses external_id UUIDField if a non-guessable identifier is needed.
    """

    external_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name="Внешний идентификатор",
        help_text="Не guessable UUID для внешних интеграций",
    )
    patient_name = models.CharField("ФИО пациента", max_length=255)
    patient_dob = models.CharField("Дата рождения", max_length=10, help_text="ДД.ММ.ГГГГ")
    patient_phone = models.CharField("Телефон", max_length=20)
    service_id = models.CharField("Услуга", max_length=50, choices=SERVICE_CHOICES)
    date_tag = models.DateField("Целевая дата", blank=True, null=True)
    date_end = models.DateField("Крайняя дата", blank=True, null=True)
    priority_cito = models.BooleanField("CITO!", default=False)
    comment = models.TextField("Комментарий", blank=True)
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=WaitingListStatus.choices,
        default=WaitingListStatus.WAITING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Запись листа ожидания"
        verbose_name_plural = "Записи листа ожидания"

    def __str__(self):
        return f"{self.patient_name} - {self.get_service_id_display()} ({self.get_status_display()})"


class WaitingListAuditLog(models.Model):
    """
    Persisted audit log for waiting list entry changes.
    Created through service helpers for server-enforced timeline.
    """

    entry = models.ForeignKey(
        WaitingListEntry,
        on_delete=models.CASCADE,
        related_name="audit_logs",
        verbose_name="Запись",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name="Пользователь",
    )
    action = models.CharField("Действие", max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Журнал изменений"
        verbose_name_plural = "Журналы изменений"

    def __str__(self):
        return f"{self.actor}: {self.action} @ {self.created_at}"
