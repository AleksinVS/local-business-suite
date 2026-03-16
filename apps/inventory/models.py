from django.db import models


class OperationalStatus(models.TextChoices):
    ACTIVE = "active", "В эксплуатации"
    MAINTENANCE = "maintenance", "На обслуживании"
    RESERVED = "reserved", "Резерв"
    DECOMMISSIONED = "decommissioned", "Выведено из эксплуатации"


class MedicalDevice(models.Model):
    name = models.CharField("Наименование", max_length=255)
    manufacturer = models.CharField("Производитель", max_length=255, blank=True)
    model = models.CharField("Модель", max_length=255, blank=True)
    serial_number = models.CharField("Серийный номер", max_length=128, unique=True)
    inventory_number = models.CharField("Инвентарный номер", max_length=128, blank=True)
    department = models.CharField("Подразделение", max_length=255)
    location = models.CharField("Местоположение", max_length=255, blank=True)
    operational_status = models.CharField(
        "Статус эксплуатации",
        max_length=32,
        choices=OperationalStatus.choices,
        default=OperationalStatus.ACTIVE,
    )
    commissioned_at = models.DateField("Дата ввода", blank=True, null=True)
    notes = models.TextField("Примечания", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "serial_number"]
        verbose_name = "Медицинское изделие"
        verbose_name_plural = "Медицинские изделия"

    def __str__(self):
        return f"{self.name} ({self.serial_number})"
