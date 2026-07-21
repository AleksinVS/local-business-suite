from django.db import models
from django.utils import timezone

from apps.core.models import Department


class OperationalStatus(models.TextChoices):
    ACTIVE = "active", "В эксплуатации"
    MAINTENANCE = "maintenance", "На обслуживании"
    RESERVED = "reserved", "Резерв"
    DECOMMISSIONED = "decommissioned", "Выведено из эксплуатации"


class MedicalDevice(models.Model):
    name = models.CharField("Наименование", max_length=255)
    device_type = models.CharField(
        "Тип медицинского изделия",
        max_length=128,
        blank=True,
        help_text="Например: рентгеновский аппарат, УЗИ-сканер, ИВЛ и т. п.",
    )
    manufacturer = models.CharField("Производитель", max_length=255, blank=True)
    production_country = models.CharField("Страна производства", max_length=128, blank=True)
    model = models.CharField("Модель", max_length=255, blank=True)
    serial_number = models.CharField(
        "Серийный номер",
        max_length=128,
        blank=True,
        null=True,
    )
    inventory_number = models.CharField(
        "Инвентарный номер",
        max_length=128,
        blank=True,
        null=True,
        unique=True,
    )
    registration_date = models.DateField("Дата регистрации", blank=True, null=True)
    registration_certificate_number = models.CharField(
        "Номер регистрационного удостоверения",
        max_length=128,
        blank=True,
    )
    production_date = models.DateField("Дата выпуска", blank=True, null=True)
    commissioned_at = models.DateField("Дата ввода в эксплуатацию", blank=True, null=True)
    service_life_years = models.PositiveSmallIntegerField(
        "Срок службы/годности, лет",
        blank=True,
        null=True,
        help_text="Нормативный срок службы или годности в годах.",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="medical_devices",
        verbose_name="Структурное подразделение",
    )
    address = models.TextField("Адрес", blank=True)
    # Устаревшее поле — сохранено для обратной совместимости с существующими записями.
    location = models.CharField("Местоположение (legacy)", max_length=255, blank=True)
    operational_status = models.CharField(
        "Статус эксплуатации",
        max_length=32,
        choices=OperationalStatus.choices,
        default=OperationalStatus.ACTIVE,
    )
    decommissioned_at = models.DateField(
        "Дата вывода из эксплуатации",
        blank=True,
        null=True,
    )
    decommission_reason = models.TextField("Причина вывода из эксплуатации", blank=True)
    notes = models.TextField("Примечания", blank=True)
    is_archived = models.BooleanField("Архивировано", default=False)
    archived_at = models.DateTimeField("Дата архивации", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "inventory_number", "id"]
        indexes = [
            models.Index(fields=["operational_status"]),
            models.Index(fields=["is_archived"]),
            models.Index(fields=["department", "is_archived"]),
            models.Index(fields=["registration_certificate_number"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(is_archived=False, archived_at__isnull=True)
                | models.Q(is_archived=True, archived_at__isnull=False),
                name="device_archive_consistent",
            ),
        ]
        verbose_name = "Медицинское изделие"
        verbose_name_plural = "Медицинские изделия"

    def save(self, *args, **kwargs):
        # unique=True на необязательном CharField: пустая строка — это значение,
        # и второе изделие без инвентарного номера нарушило бы уникальность.
        # NULL уникальностью не ограничивается, поэтому "" нормализуется в None.
        if not self.inventory_number:
            self.inventory_number = None
        super().save(*args, **kwargs)

    def __str__(self):
        parts = [self.name]
        if self.inventory_number:
            parts.append(f"инв. {self.inventory_number}")
        if self.serial_number:
            parts.append(f"SN {self.serial_number}")
        return " · ".join(parts)

    def archive(self):
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=["is_archived", "archived_at", "updated_at"])