from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


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


class WorkOrder(models.Model):
    number = models.CharField("Номер", max_length=32, unique=True, editable=False)
    title = models.CharField("Заголовок", max_length=255)
    description = models.TextField("Описание")
    department = models.CharField("Подразделение", max_length=255)
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
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(blank=True, null=True)
    closed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки"

    def save(self, *args, **kwargs):
        if not self.number:
            stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
            self.number = f"WO-{stamp}"
        if self.status == WorkOrderStatus.RESOLVED and not self.resolved_at:
            self.resolved_at = timezone.now()
        if self.status != WorkOrderStatus.RESOLVED:
            self.resolved_at = self.resolved_at
        if self.status == WorkOrderStatus.CLOSED and not self.closed_at:
            self.closed_at = timezone.now()
        if self.status != WorkOrderStatus.CLOSED:
            self.closed_at = None
        super().save(*args, **kwargs)

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
