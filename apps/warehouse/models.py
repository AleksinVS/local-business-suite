from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import Department


QUANTITY_MAX_DIGITS = 20
QUANTITY_DECIMAL_PLACES = 6


def default_quantity_precision() -> int:
    from apps.warehouse.runtime_settings import get_warehouse_runtime_settings

    return get_warehouse_runtime_settings()["default_quantity_precision"]


class ActiveNamedModel(models.Model):
    code = models.CharField("Код", max_length=64, unique=True)
    name = models.CharField("Наименование", max_length=255)
    is_active = models.BooleanField("Активно", default=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        abstract = True
        ordering = ["name", "code", "id"]

    def __str__(self):
        return self.name


class WarehouseItemCategory(ActiveNamedModel):
    class Meta(ActiveNamedModel.Meta):
        verbose_name = "Категория складской позиции"
        verbose_name_plural = "Категории складских позиций"


class UnitOfMeasure(ActiveNamedModel):
    quantity_precision = models.PositiveSmallIntegerField(
        "Точность количества",
        default=default_quantity_precision,
        help_text="Допустимое число знаков после запятой от 0 до 6.",
    )

    class Meta(ActiveNamedModel.Meta):
        verbose_name = "Единица измерения"
        verbose_name_plural = "Единицы измерения"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_precision__gte=0, quantity_precision__lte=6),
                name="warehouse_uom_precision_0_6",
            ),
        ]

    def clean(self):
        super().clean()
        if not 0 <= self.quantity_precision <= QUANTITY_DECIMAL_PLACES:
            raise ValidationError(
                {"quantity_precision": "Точность должна быть в диапазоне от 0 до 6."}
            )
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values_list(
                "quantity_precision", flat=True
            ).first()
            if previous is not None and self.quantity_precision < previous:
                has_entries = StockEntry.objects.filter(unit_id=self.pk).exists()
                if has_entries:
                    raise ValidationError(
                        {
                            "quantity_precision": (
                                "Нельзя уменьшать точность единицы после проведения операций."
                            )
                        }
                    )


class WarehouseItem(ActiveNamedModel):
    short_name = models.CharField("Краткое наименование", max_length=255, blank=True)
    category = models.ForeignKey(
        WarehouseItemCategory,
        on_delete=models.PROTECT,
        related_name="items",
        verbose_name="Категория",
    )
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="items",
        verbose_name="Единица измерения",
    )
    manufacturer = models.CharField("Производитель", max_length=255, blank=True)
    dosage_form = models.CharField("Форма выпуска", max_length=255, blank=True)
    application_method = models.CharField("Способ применения", max_length=255, blank=True)

    class Meta(ActiveNamedModel.Meta):
        verbose_name = "Складская позиция"
        verbose_name_plural = "Складские позиции"
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["name"]),
        ]


class FundingSource(ActiveNamedModel):
    class Meta(ActiveNamedModel.Meta):
        verbose_name = "Источник финансирования"
        verbose_name_plural = "Источники финансирования"


class Warehouse(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="warehouses",
        verbose_name="Подразделение",
    )
    code = models.CharField("Код", max_length=64)
    name = models.CharField("Наименование", max_length=255)
    is_active = models.BooleanField("Активно", default=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        ordering = ["department__name", "name", "id"]
        verbose_name = "Склад"
        verbose_name_plural = "Склады"
        constraints = [
            models.UniqueConstraint(
                fields=["department", "code"],
                name="warehouse_unique_department_code",
            ),
        ]
        indexes = [models.Index(fields=["department", "is_active"])]

    def __str__(self):
        return f"{self.department}: {self.name}"

    def clean(self):
        super().clean()
        if self.pk:
            previous_department_id = type(self).objects.filter(pk=self.pk).values_list(
                "department_id", flat=True
            ).first()
            if previous_department_id and previous_department_id != self.department_id:
                if StockEntry.objects.filter(warehouse_id=self.pk).exists():
                    raise ValidationError(
                        {"department": "Нельзя менять подразделение склада с операциями."}
                    )


class StorageLocation(models.Model):
    class LocationType(models.TextChoices):
        ROOM = "room", "Помещение"
        RACK = "rack", "Стеллаж"
        SHELF = "shelf", "Полка"
        BIN = "bin", "Ячейка"
        OTHER = "other", "Другое"

    class Purpose(models.TextChoices):
        AVAILABLE = "available", "Доступно для выдачи"
        QUARANTINE = "quarantine", "Карантин"
        UNASSIGNED = "unassigned", "Адрес не назначен"

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="locations",
        verbose_name="Склад",
    )
    code = models.CharField("Код адреса", max_length=255)
    name = models.CharField("Наименование", max_length=255)
    location_type = models.CharField(
        "Тип",
        max_length=16,
        choices=LocationType.choices,
        default=LocationType.RACK,
    )
    purpose = models.CharField(
        "Назначение",
        max_length=16,
        choices=Purpose.choices,
        default=Purpose.AVAILABLE,
    )
    sort_order = models.PositiveIntegerField("Порядок", default=0)
    is_active = models.BooleanField("Активно", default=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        ordering = ["warehouse", "sort_order", "code", "id"]
        verbose_name = "Адрес хранения"
        verbose_name_plural = "Адреса хранения"
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "code"],
                name="warehouse_unique_location_code",
            ),
        ]
        indexes = [
            models.Index(fields=["warehouse", "purpose", "is_active"]),
        ]

    def __str__(self):
        return f"{self.warehouse.name}: {self.code} — {self.name}"

    def clean(self):
        super().clean()
        if self.pk:
            previous_warehouse_id = type(self).objects.filter(pk=self.pk).values_list(
                "warehouse_id", flat=True
            ).first()
            if previous_warehouse_id and previous_warehouse_id != self.warehouse_id:
                if StockEntry.objects.filter(location_id=self.pk).exists():
                    raise ValidationError(
                        {"warehouse": "Нельзя переносить использованный адрес в другой склад."}
                    )


class StockLot(models.Model):
    item = models.ForeignKey(
        WarehouseItem,
        on_delete=models.PROTECT,
        related_name="lots",
        verbose_name="Позиция",
    )
    batch_number = models.CharField("Серия/партия", max_length=255, blank=True)
    expires_on = models.DateField("Срок годности", blank=True, null=True, db_index=True)
    incomplete_reason = models.TextField(
        "Причина неполных данных",
        blank=True,
        help_text="Обязательна, если серия или срок годности не указаны.",
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ["item__name", "expires_on", "batch_number", "id"]
        verbose_name = "Партия"
        verbose_name_plural = "Партии"
        indexes = [
            models.Index(fields=["item", "expires_on"]),
            models.Index(fields=["item", "batch_number"]),
        ]

    def __str__(self):
        batch = self.batch_number or "без серии"
        return f"{self.item} / {batch}"

    def clean(self):
        super().clean()
        if (not self.batch_number or not self.expires_on) and not self.incomplete_reason.strip():
            raise ValidationError(
                {
                    "incomplete_reason": (
                        "Укажите причину, если серия или срок годности отсутствуют."
                    )
                }
            )
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values(
                "item_id", "batch_number", "expires_on"
            ).first()
            if previous and any(
                (
                    previous["item_id"] != self.item_id,
                    previous["batch_number"] != self.batch_number,
                    previous["expires_on"] != self.expires_on,
                )
            ) and StockEntry.objects.filter(lot_id=self.pk).exists():
                raise ValidationError(
                    "Нельзя менять идентификационные данные партии после проведения операций."
                )


class StockDocument(models.Model):
    class DocumentType(models.TextChoices):
        OPENING = "opening", "Начальный остаток"
        RECEIPT = "receipt", "Приход"
        ISSUE = "issue", "Выдача/расход"
        RELOCATION = "relocation", "Перемещение адреса"
        WRITEOFF = "writeoff", "Списание"
        ADJUSTMENT = "adjustment", "Корректировка"
        REVERSAL = "reversal", "Сторно"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        POSTED = "posted", "Проведён"
        CANCELLED = "cancelled", "Отменён"

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="stock_documents",
        verbose_name="Подразделение",
    )
    document_type = models.CharField("Тип", max_length=16, choices=DocumentType.choices)
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    number = models.CharField("Номер документа/требования", max_length=128, blank=True)
    operation_date = models.DateField("Дата операции", db_index=True)
    comment = models.TextField("Комментарий", blank=True)
    reason = models.TextField("Причина", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_stock_documents",
        verbose_name="Создал",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="posted_stock_documents",
        verbose_name="Провёл",
        blank=True,
        null=True,
    )
    posted_at = models.DateTimeField("Проведено", blank=True, null=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)
    idempotency_key = models.UUIDField(
        "Ключ идемпотентности",
        blank=True,
        null=True,
        unique=True,
    )
    external_source_id = models.CharField(
        "Идентификатор внешнего источника",
        max_length=255,
        blank=True,
        db_index=True,
    )
    reverses_document = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        related_name="reversal_document",
        verbose_name="Сторнируемый документ",
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["-operation_date", "-id"]
        verbose_name = "Складской документ"
        verbose_name_plural = "Складские документы"
        indexes = [
            models.Index(fields=["department", "operation_date", "status"]),
            models.Index(fields=["document_type", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(document_type="reversal", reverses_document__isnull=False)
                    | Q(document_type__in=[
                        "opening",
                        "receipt",
                        "issue",
                        "relocation",
                        "writeoff",
                        "adjustment",
                    ], reverses_document__isnull=True)
                ),
                name="warehouse_reversal_source_matches_type",
            ),
        ]

    def __str__(self):
        return f"{self.get_document_type_display()} от {self.operation_date} №{self.number or '—'}"

    @property
    def is_reversed(self):
        return hasattr(self, "reversal_document") and self.reversal_document.status == self.Status.POSTED

    def clean(self):
        super().clean()
        if self.document_type == self.DocumentType.REVERSAL and not self.reverses_document_id:
            raise ValidationError({"reverses_document": "Для сторно нужен исходный документ."})
        if self.document_type != self.DocumentType.REVERSAL and self.reverses_document_id:
            raise ValidationError(
                {"reverses_document": "Ссылка на исходный документ допустима только для сторно."}
            )
        if self.document_type in {
            self.DocumentType.WRITEOFF,
            self.DocumentType.ADJUSTMENT,
            self.DocumentType.REVERSAL,
        }:
            if not self.reason.strip():
                raise ValidationError(
                    {"reason": "Для списания, корректировки или сторно нужна причина."}
                )

    def save(self, *args, **kwargs):
        if self.pk:
            persisted_status = type(self).objects.filter(pk=self.pk).values_list(
                "status", flat=True
            ).first()
            if persisted_status == self.Status.POSTED:
                raise ValidationError("Проведённый складской документ нельзя изменять.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == self.Status.POSTED:
            raise ValidationError("Проведённый складской документ нельзя удалять.")
        return super().delete(*args, **kwargs)


class StockDocumentLine(models.Model):
    document = models.ForeignKey(
        StockDocument,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="Документ",
    )
    sequence = models.PositiveIntegerField("Номер строки", default=1)
    item = models.ForeignKey(
        WarehouseItem,
        on_delete=models.PROTECT,
        related_name="document_lines",
        verbose_name="Позиция",
    )
    lot = models.ForeignKey(
        StockLot,
        on_delete=models.PROTECT,
        related_name="document_lines",
        verbose_name="Партия",
    )
    funding_source = models.ForeignKey(
        FundingSource,
        on_delete=models.PROTECT,
        related_name="document_lines",
        verbose_name="Источник финансирования",
    )
    quantity = models.DecimalField(
        "Количество",
        max_digits=QUANTITY_MAX_DIGITS,
        decimal_places=QUANTITY_DECIMAL_PLACES,
    )
    source_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="outgoing_document_lines",
        verbose_name="Исходный адрес",
        blank=True,
        null=True,
    )
    destination_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="incoming_document_lines",
        verbose_name="Целевой адрес",
        blank=True,
        null=True,
    )
    fefo_override_reason = models.TextField(
        "Причина отклонения от FEFO",
        blank=True,
        help_text="Обязательна, если выбрана не самая ранняя доступная партия.",
    )

    class Meta:
        ordering = ["document", "sequence", "id"]
        verbose_name = "Строка складского документа"
        verbose_name_plural = "Строки складского документа"
        constraints = [
            models.UniqueConstraint(
                fields=["document", "sequence"],
                name="warehouse_unique_document_line_sequence",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="warehouse_document_line_quantity_positive",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.lot_id and self.item_id and self.lot.item_id != self.item_id:
            errors["lot"] = "Партия должна относиться к выбранной позиции."
        document_type = self.document.document_type if self.document_id else None
        if document_type in {StockDocument.DocumentType.OPENING, StockDocument.DocumentType.RECEIPT}:
            if self.source_location_id or not self.destination_location_id:
                errors["destination_location"] = "Для прихода нужен только целевой адрес."
        elif document_type in {StockDocument.DocumentType.ISSUE, StockDocument.DocumentType.WRITEOFF}:
            if not self.source_location_id or self.destination_location_id:
                errors["source_location"] = "Для расхода нужен только исходный адрес."
        elif document_type == StockDocument.DocumentType.RELOCATION:
            if not self.source_location_id or not self.destination_location_id:
                errors["destination_location"] = "Для перемещения нужны оба адреса."
            elif self.source_location_id == self.destination_location_id:
                errors["destination_location"] = "Адреса перемещения должны различаться."
        elif document_type == StockDocument.DocumentType.ADJUSTMENT:
            if bool(self.source_location_id) == bool(self.destination_location_id):
                errors["destination_location"] = (
                    "Для корректировки укажите ровно один исходный или целевой адрес."
                )
        if self.source_location_id and self.source_location.warehouse.department_id != self.document.department_id:
            errors["source_location"] = "Исходный адрес должен быть в подразделении документа."
        if (
            self.destination_location_id
            and self.destination_location.warehouse.department_id != self.document.department_id
        ):
            errors["destination_location"] = "Целевой адрес должен быть в подразделении документа."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.document_id:
            status = StockDocument.objects.filter(pk=self.document_id).values_list(
                "status", flat=True
            ).first()
            if status == StockDocument.Status.POSTED:
                raise ValidationError("Строки проведённого документа нельзя изменять.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.document_id and self.document.status == StockDocument.Status.POSTED:
            raise ValidationError("Строки проведённого документа нельзя удалять.")
        return super().delete(*args, **kwargs)


class ImmutableEntryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Проведённые складские проводки нельзя изменять.")

    def delete(self):
        raise ValidationError("Проведённые складские проводки нельзя удалять.")


class StockEntry(models.Model):
    document = models.ForeignKey(
        StockDocument,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name="Документ",
    )
    document_line = models.ForeignKey(
        StockDocumentLine,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name="Строка документа",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="stock_entries",
        verbose_name="Подразделение",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name="Склад",
    )
    location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name="Адрес",
    )
    lot = models.ForeignKey(
        StockLot,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name="Партия",
    )
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name="stock_entries",
        verbose_name="Единица",
    )
    funding_source = models.ForeignKey(
        FundingSource,
        on_delete=models.PROTECT,
        related_name="entries",
        verbose_name="Источник финансирования",
    )
    quantity = models.DecimalField(
        "Количество",
        max_digits=QUANTITY_MAX_DIGITS,
        decimal_places=QUANTITY_DECIMAL_PLACES,
    )
    operation_date = models.DateField("Дата операции", db_index=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    objects = ImmutableEntryQuerySet.as_manager()

    class Meta:
        ordering = ["operation_date", "id"]
        verbose_name = "Складская проводка"
        verbose_name_plural = "Складские проводки"
        indexes = [
            models.Index(fields=["department", "operation_date"]),
            models.Index(fields=["location", "lot", "funding_source"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(quantity=0),
                name="warehouse_entry_quantity_nonzero",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Проведённые складские проводки нельзя изменять.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Проведённые складские проводки нельзя удалять.")


class StockBalance(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="stock_balances",
        verbose_name="Подразделение",
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="balances",
        verbose_name="Склад",
    )
    location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name="balances",
        verbose_name="Адрес",
    )
    lot = models.ForeignKey(
        StockLot,
        on_delete=models.PROTECT,
        related_name="balances",
        verbose_name="Партия",
    )
    funding_source = models.ForeignKey(
        FundingSource,
        on_delete=models.PROTECT,
        related_name="balances",
        verbose_name="Источник финансирования",
    )
    quantity = models.DecimalField(
        "Остаток",
        max_digits=QUANTITY_MAX_DIGITS,
        decimal_places=QUANTITY_DECIMAL_PLACES,
        default=0,
    )
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        ordering = ["department", "warehouse", "location", "lot", "funding_source"]
        verbose_name = "Текущий остаток"
        verbose_name_plural = "Текущие остатки"
        constraints = [
            models.UniqueConstraint(
                fields=["department", "warehouse", "location", "lot", "funding_source"],
                name="warehouse_unique_balance_key",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=0),
                name="warehouse_balance_nonnegative",
            ),
        ]
        indexes = [
            models.Index(fields=["department", "quantity"]),
            models.Index(fields=["location", "quantity"]),
            models.Index(fields=["lot", "quantity"]),
        ]


class WarehouseAuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="warehouse_audit_events",
        blank=True,
        null=True,
        verbose_name="Инициатор",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="warehouse_audit_events",
        blank=True,
        null=True,
        verbose_name="Подразделение",
        help_text="Пусто только для общесистемных событий.",
    )
    action = models.CharField("Действие", max_length=64, db_index=True)
    object_type = models.CharField("Тип объекта", max_length=128)
    object_id = models.CharField("Идентификатор объекта", max_length=128, blank=True)
    reason = models.TextField("Причина", blank=True)
    correlation_id = models.UUIDField("Correlation ID", default=uuid.uuid4, db_index=True)
    summary = models.JSONField("Безопасное резюме", default=dict, blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Событие аудита склада"
        verbose_name_plural = "События аудита склада"


class WarehouseReportProfile(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="warehouse_report_profiles",
        verbose_name="Подразделение",
    )
    name = models.CharField("Название профиля", max_length=255)
    valid_from = models.DateField("Действует с", blank=True, null=True)
    valid_to = models.DateField("Действует по", blank=True, null=True)
    approval_label = models.CharField("Гриф утверждения", max_length=255, blank=True)
    signer_position = models.CharField("Должность подписанта", max_length=255, blank=True)
    signer_name = models.CharField("ФИО подписанта", max_length=255, blank=True)
    footer_note = models.TextField("Примечание", blank=True)
    is_active = models.BooleanField("Активно", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_warehouse_report_profiles",
        verbose_name="Создал",
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        ordering = ["department", "-valid_from", "name", "id"]
        verbose_name = "Профиль складского отчёта"
        verbose_name_plural = "Профили складских отчётов"
        indexes = [models.Index(fields=["department", "is_active", "valid_from"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True)
                | Q(valid_from__isnull=True)
                | Q(valid_to__gte=models.F("valid_from")),
                name="warehouse_report_profile_valid_range",
            )
        ]

    def __str__(self):
        return f"{self.department}: {self.name}"


class WarehouseImportRun(models.Model):
    class Status(models.TextChoices):
        INSPECTED = "inspected", "Проверен"
        PREPARED = "prepared", "Подготовлен"
        IMPORTED = "imported", "Импортирован"
        RECONCILED = "reconciled", "Сверен"
        FAILED = "failed", "Ошибка"

    run_id = models.UUIDField("Идентификатор запуска", default=uuid.uuid4, unique=True)
    source_fingerprint = models.CharField("Отпечаток источника", max_length=64, db_index=True)
    source_name = models.CharField("Имя источника", max_length=255)
    adapter = models.CharField("Адаптер", max_length=64)
    transformation_version = models.CharField("Версия преобразования", max_length=64)
    status = models.CharField(
        "Статус", max_length=16, choices=Status.choices, default=Status.INSPECTED
    )
    manifest = models.JSONField("Манифест", default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="warehouse_import_runs",
        verbose_name="Запустил",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    completed_at = models.DateTimeField("Завершено", blank=True, null=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Запуск импорта склада"
        verbose_name_plural = "Запуски импорта склада"
        constraints = [
            models.UniqueConstraint(
                fields=["source_fingerprint", "adapter", "transformation_version"],
                name="warehouse_unique_import_source_version",
            )
        ]


class WarehouseImportRecord(models.Model):
    class Result(models.TextChoices):
        CREATED = "created", "Создано"
        REUSED = "reused", "Переиспользовано"
        SKIPPED = "skipped", "Пропущено"
        BLOCKED = "blocked", "Заблокировано"

    run = models.ForeignKey(
        WarehouseImportRun,
        on_delete=models.CASCADE,
        related_name="records",
        verbose_name="Запуск",
    )
    source_table = models.CharField("Таблица источника", max_length=128)
    legacy_key = models.CharField("Legacy-ключ", max_length=255, blank=True)
    row_hash = models.CharField("Хеш строки", max_length=64)
    target_model = models.CharField("Целевая модель", max_length=128, blank=True)
    target_pk = models.CharField("Целевой PK", max_length=128, blank=True)
    result = models.CharField("Результат", max_length=16, choices=Result.choices)
    details = models.JSONField("Детали", default=dict, blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ["run", "source_table", "legacy_key", "id"]
        verbose_name = "Строка импорта склада"
        verbose_name_plural = "Строки импорта склада"
        constraints = [
            models.UniqueConstraint(
                fields=["run", "source_table", "row_hash"],
                name="warehouse_unique_import_record",
            )
        ]


class WarehouseImportIssue(models.Model):
    class Severity(models.TextChoices):
        INFO = "info", "Информация"
        WARNING = "warning", "Предупреждение"
        CRITICAL = "critical", "Критическая"

    run = models.ForeignKey(
        WarehouseImportRun,
        on_delete=models.CASCADE,
        related_name="issues",
        verbose_name="Запуск",
    )
    severity = models.CharField("Важность", max_length=16, choices=Severity.choices)
    code = models.CharField("Код", max_length=64, db_index=True)
    source_table = models.CharField("Таблица источника", max_length=128, blank=True)
    legacy_key = models.CharField("Legacy-ключ", max_length=255, blank=True)
    message = models.TextField("Сообщение")
    context = models.JSONField("Контекст", default=dict, blank=True)
    resolved_at = models.DateTimeField("Разрешено", blank=True, null=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="resolved_warehouse_import_issues",
        verbose_name="Разрешил",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ["run", "-severity", "source_table", "legacy_key", "id"]
        verbose_name = "Проблема импорта склада"
        verbose_name_plural = "Проблемы импорта склада"
        indexes = [models.Index(fields=["run", "severity", "resolved_at"])]
