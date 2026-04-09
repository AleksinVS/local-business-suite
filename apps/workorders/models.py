from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import Department

ATTACHMENT_MAX_SIZE = 10 * 1024 * 1024
ATTACHMENT_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ATTACHMENT_ALLOWED_TYPES = ATTACHMENT_IMAGE_TYPES | {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
}


class WorkOrderStatus(models.TextChoices):
    NEW = "new", "Новая"
    ACCEPTED = "accepted", "Принята"
    IN_PROGRESS = "in_progress", "В работе"
    ON_HOLD = "on_hold", "Ожидание"
    RESOLVED = "resolved", "Выполнена"
    CLOSED = "closed", "Закрыта"
    CANCELLED = "cancelled", "Отменена"


class WorkOrderPriority(models.TextChoices):
    LOW = "low", "Низкий"
    MEDIUM = "medium", "Средний"
    HIGH = "high", "Высокий"
    CRITICAL = "critical", "Критичный"


class KanbanColumnConfig(models.Model):
    code = models.SlugField("Код", max_length=50, unique=True)
    title = models.CharField("Название", max_length=120)
    position = models.PositiveIntegerField("Позиция", default=0)
    statuses = models.JSONField("Статусы", default=list)
    wip_limit = models.PositiveIntegerField("WIP Лимит", default=0, help_text="0 - без лимита")

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "Колонка канбана"
        verbose_name_plural = "Колонки канбана"

    def __str__(self):
        return self.title


class WorkOrder(models.Model):
    number = models.CharField("Номер", max_length=32, unique=True, editable=False)
    title = models.CharField("Заголовок", max_length=255)
    description = models.TextField("Описание")
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="workorders",
        verbose_name="Подразделение",
    )
    priority = models.CharField(
        "Приоритет",
        max_length=16,
        choices=WorkOrderPriority.choices,
        default=WorkOrderPriority.MEDIUM,
    )
    status = models.CharField(
        "Статус",
        max_length=24,
        choices=WorkOrderStatus.choices,
        default=WorkOrderStatus.NEW,
    )
    rating = models.PositiveSmallIntegerField(
        "Оценка",
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    closure_confirmed = models.BooleanField("Закрытие подтверждено", default=False)
    closure_confirmed_at = models.DateTimeField(blank=True, null=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_workorders",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_workorders",
        blank=True,
        null=True,
    )
    device = models.ForeignKey(
        "inventory.MedicalDevice",
        on_delete=models.PROTECT,
        related_name="workorders",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(blank=True, null=True)
    closed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки"

    @staticmethod
    def format_number(pk):
        return str(pk)

    def save(self, *args, **kwargs):
        if self.status == WorkOrderStatus.RESOLVED and not self.resolved_at:
            self.resolved_at = timezone.now()
        if self.status == WorkOrderStatus.CLOSED and not self.closed_at:
            self.closed_at = timezone.now()
        if self.status != WorkOrderStatus.CLOSED:
            self.closed_at = None
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating and not self.number:
            self.number = self.format_number(self.pk)
            super().save(update_fields=["number"])

    def __str__(self):
        return f"{self.number}: {self.title}"


class WorkOrderComment(models.Model):
    workorder = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField("Комментарий")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Комментарий к заявке"
        verbose_name_plural = "Комментарии к заявке"


class WorkOrderAttachment(models.Model):
    workorder = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    file = models.FileField(upload_to="workorders/%Y/%m/%d/")
    content_type = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Вложение"
        verbose_name_plural = "Вложения"

    @property
    def is_image(self):
        return self.content_type in ATTACHMENT_IMAGE_TYPES

    @property
    def filename(self):
        return self.file.name.rsplit("/", 1)[-1]


class WorkOrderTransitionLog(models.Model):
    workorder = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="transitions",
    )
    from_status = models.CharField(max_length=24, choices=WorkOrderStatus.choices)
    to_status = models.CharField(max_length=24, choices=WorkOrderStatus.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Переход заявки"
        verbose_name_plural = "Переходы заявок"
