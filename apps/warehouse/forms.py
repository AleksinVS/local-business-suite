from django import forms
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.core.exceptions import ValidationError
from decimal import Decimal

from apps.core.models import Department
from apps.warehouse.models import (
    FundingSource,
    StockDocument,
    StockDocumentLine,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
    WarehouseItem,
    WarehouseItemCategory,
    WarehouseReportProfile,
)
from apps.warehouse.policies import (
    WAREHOUSE_ADJUST_SCOPE,
    WAREHOUSE_MANAGE_LOCATIONS_SCOPE,
    WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE,
    WAREHOUSE_OPERATE_SCOPE,
    department_ids_for_warehouse_scope,
    warehouse_scope_allows_department,
)
from apps.warehouse.selectors import manageable_location_warehouses_queryset
from apps.warehouse.series import normalize_series


def _department_queryset(actor, *capabilities):
    allowed: set[int] = set()
    for capability in capabilities:
        ids = department_ids_for_warehouse_scope(actor, capability)
        if ids is None:
            return Department.objects.all()
        allowed.update(ids)
    return Department.objects.filter(pk__in=allowed)


class StockDocumentForm(forms.ModelForm):
    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.fields["department"].queryset = _department_queryset(
            actor, WAREHOUSE_OPERATE_SCOPE, WAREHOUSE_ADJUST_SCOPE
        )
        choices = []
        if department_ids_for_warehouse_scope(actor, WAREHOUSE_OPERATE_SCOPE) != set():
            choices.extend(
                choice
                for choice in StockDocument.DocumentType.choices
                if choice[0]
                in {
                    StockDocument.DocumentType.OPENING,
                    StockDocument.DocumentType.RECEIPT,
                    StockDocument.DocumentType.ISSUE,
                    StockDocument.DocumentType.RELOCATION,
                }
            )
        if department_ids_for_warehouse_scope(actor, WAREHOUSE_ADJUST_SCOPE) != set():
            choices.extend(
                choice
                for choice in StockDocument.DocumentType.choices
                if choice[0]
                in {
                    StockDocument.DocumentType.WRITEOFF,
                    StockDocument.DocumentType.ADJUSTMENT,
                }
            )
        self.fields["document_type"].choices = choices

    class Meta:
        model = StockDocument
        fields = ["department", "document_type", "number", "operation_date", "comment", "reason"]
        widgets = {"operation_date": forms.DateInput(attrs={"type": "date"})}

    def clean(self):
        cleaned = super().clean()
        department = cleaned.get("department")
        document_type = cleaned.get("document_type")
        if not department or not document_type:
            return cleaned
        capability = (
            WAREHOUSE_ADJUST_SCOPE
            if document_type
            in {StockDocument.DocumentType.WRITEOFF, StockDocument.DocumentType.ADJUSTMENT}
            else WAREHOUSE_OPERATE_SCOPE
        )
        if not warehouse_scope_allows_department(
            actor=self.actor, capability=capability, department=department
        ):
            raise forms.ValidationError("Нет доступа к операции в выбранном подразделении.")
        return cleaned


class StockDocumentLineForm(forms.ModelForm):
    def __init__(self, *args, actor=None, department=None, document_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.department = department
        if document_type is None and self.instance.document_id:
            document_type = self.instance.document.document_type
        self.document_type = document_type
        if department is not None:
            warehouses = Warehouse.objects.filter(department=department)
        else:
            department_qs = _department_queryset(
                actor, WAREHOUSE_OPERATE_SCOPE, WAREHOUSE_ADJUST_SCOPE
            )
            warehouses = Warehouse.objects.filter(department__in=department_qs)
        locations = StorageLocation.objects.filter(warehouse__in=warehouses)
        if document_type != StockDocument.DocumentType.ADJUSTMENT:
            locations = locations.filter(
                is_active=True, purpose=StorageLocation.Purpose.AVAILABLE
            )
        self.fields["source_location"].queryset = locations
        self.fields["destination_location"].queryset = locations
        item_ids = [self.instance.item_id] if self.instance.item_id else []
        source_ids = [self.instance.funding_source_id] if self.instance.funding_source_id else []
        self.fields["item"].queryset = WarehouseItem.objects.filter(
            Q(is_active=True) | Q(pk__in=item_ids)
        )
        self.fields["funding_source"].queryset = FundingSource.objects.filter(
            Q(is_active=True) | Q(pk__in=source_ids)
        )
        raw_item = self.data.get(self.add_prefix("item")) if self.is_bound else None
        selected_item = self.fields["item"].queryset.filter(pk=raw_item).first() if raw_item else None
        instance_item = self.fields["item"].queryset.filter(pk=self.instance.item_id).first() if self.instance.item_id else None
        self.selected_item_label = str(selected_item or instance_item or "")
        def selected_label(field_name):
            raw = self.data.get(self.add_prefix(field_name)) if self.is_bound else None
            selected = self.fields[field_name].queryset.filter(pk=raw).first() if raw else None
            instance_id = getattr(self.instance, f"{field_name}_id", None)
            current = self.fields[field_name].queryset.filter(pk=instance_id).first() if instance_id else None
            return str(selected or current or "")

        self.selected_funding_source_label = selected_label("funding_source")
        self.selected_source_location_label = selected_label("source_location")
        self.selected_destination_location_label = selected_label("destination_location")

        # Address fields are operation-specific.  Removing them from the form
        # also prevents stale values from a previously selected operation from
        # being submitted by the browser.
        if document_type in {
            StockDocument.DocumentType.OPENING,
            StockDocument.DocumentType.RECEIPT,
        }:
            self.fields.pop("source_location", None)
            self.fields.pop("fefo_override_reason", None)
        elif document_type in {
            StockDocument.DocumentType.ISSUE,
            StockDocument.DocumentType.WRITEOFF,
        }:
            self.fields.pop("destination_location", None)
        elif document_type == StockDocument.DocumentType.RELOCATION:
            self.fields.pop("fefo_override_reason", None)
        elif document_type == StockDocument.DocumentType.ADJUSTMENT:
            self.fields.pop("fefo_override_reason", None)

        # ``sequence`` is intentionally absent from the bound form: a client
        # must not be able to influence uniqueness validation or row order.

    class Meta:
        model = StockDocumentLine
        fields = [
            "item",
            "series",
            "expires_on",
            "incomplete_reason",
            "funding_source",
            "quantity",
            "source_location",
            "destination_location",
            "fefo_override_reason",
        ]
        widgets = {"expires_on": forms.DateInput(attrs={"type": "date"})}

    def clean(self):
        cleaned = super().clean()
        if self.cleaned_data.get("DELETE"):
            return cleaned
        item = cleaned.get("item")
        quantity = cleaned.get("quantity")
        if quantity is not None and quantity <= 0:
            self.add_error("quantity", "Количество должно быть больше нуля.")
        if item and quantity is not None:
            precision = item.unit.quantity_precision
            quantum = Decimal(1).scaleb(-precision)
            if quantity != quantity.quantize(quantum):
                self.add_error("quantity", f"Единица «{item.unit}» допускает не более {precision} знаков после запятой.")
        series = cleaned.get("series", "")
        if series:
            try:
                cleaned["series"], _ = normalize_series(series)
            except ValidationError as exc:
                self.add_error("series", exc)
        if item and self.document_type in {
            StockDocument.DocumentType.OPENING,
            StockDocument.DocumentType.RECEIPT,
        } and not cleaned.get("destination_location"):
            self.add_error("destination_location", "Укажите адрес размещения.")
        if item and self.document_type in {
            StockDocument.DocumentType.ISSUE,
            StockDocument.DocumentType.WRITEOFF,
        } and not cleaned.get("source_location"):
            self.add_error("source_location", "Укажите исходный адрес.")
        return cleaned


class StockDocumentLineFormSetBase(BaseInlineFormSet):
    """Assign row numbers on the server; the browser never owns sequence."""

    def clean(self):
        super().clean()
        active = [form for form in self.forms if form.is_valid() and not form.cleaned_data.get("DELETE")]
        if not active:
            raise ValidationError("Добавьте хотя бы одну строку документа.")

    def save(self, commit=True):
        instances = super().save(commit=False)
        deleted = self.deleted_objects
        if commit:
            for instance in deleted:
                instance.delete()
        for sequence, instance in enumerate(instances, start=1):
            instance.sequence = sequence
            if commit:
                instance.save()
        if commit:
            self.save_m2m()
        return instances


StockDocumentLineFormSet = inlineformset_factory(
    StockDocument,
    StockDocumentLine,
    form=StockDocumentLineForm,
    formset=StockDocumentLineFormSetBase,
    extra=1,
    can_delete=True,
)


class WarehouseForm(forms.ModelForm):
    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = _department_queryset(
            actor, WAREHOUSE_MANAGE_LOCATIONS_SCOPE
        )
        location_queryset = StorageLocation.objects.none()
        if self.instance and self.instance.pk:
            location_queryset = StorageLocation.objects.filter(
                warehouse=self.instance,
                is_active=True,
                purpose=StorageLocation.Purpose.AVAILABLE,
            ).order_by("sort_order", "code", "pk")
        self.fields["default_receiving_location"].queryset = location_queryset
        self.selected_department_label = _selected_label(self, "department")
        self.selected_default_receiving_location_label = _selected_label(
            self, "default_receiving_location"
        )

    class Meta:
        model = Warehouse
        fields = [
            "department",
            "code",
            "name",
            "default_receiving_location",
            "is_active",
        ]


class StorageLocationForm(forms.ModelForm):
    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = manageable_location_warehouses_queryset(actor)
        self.selected_warehouse_label = _selected_label(self, "warehouse")

    class Meta:
        model = StorageLocation
        fields = [
            "warehouse",
            "code",
            "name",
            "location_type",
            "purpose",
            "sort_order",
            "is_active",
        ]


class WarehouseReportProfileForm(forms.ModelForm):
    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = _department_queryset(
            actor, WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE
        )
        self.selected_department_label = _selected_label(self, "department")

    class Meta:
        model = WarehouseReportProfile
        fields = [
            "department",
            "name",
            "valid_from",
            "valid_to",
            "approval_label",
            "signer_position",
            "signer_name",
            "footer_note",
            "is_active",
        ]
        widgets = {
            "valid_from": forms.DateInput(attrs={"type": "date"}),
            "valid_to": forms.DateInput(attrs={"type": "date"}),
        }


class WarehouseItemCategoryForm(forms.ModelForm):
    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = WarehouseItemCategory
        fields = ["code", "name", "is_active"]


class UnitOfMeasureForm(forms.ModelForm):
    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = UnitOfMeasure
        fields = ["code", "name", "quantity_precision", "is_active"]


class FundingSourceForm(forms.ModelForm):
    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = FundingSource
        fields = ["code", "name", "is_active"]


class WarehouseItemForm(forms.ModelForm):
    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        category_ids = [self.instance.category_id] if self.instance.category_id else []
        unit_ids = [self.instance.unit_id] if self.instance.unit_id else []
        self.fields["category"].queryset = WarehouseItemCategory.objects.filter(
            Q(is_active=True) | Q(pk__in=category_ids)
        )
        self.fields["unit"].queryset = UnitOfMeasure.objects.filter(
            Q(is_active=True) | Q(pk__in=unit_ids)
        )
        self.selected_category_label = _selected_label(self, "category")
        self.selected_unit_label = _selected_label(self, "unit")

    class Meta:
        model = WarehouseItem
        fields = [
            "code",
            "name",
            "short_name",
            "category",
            "unit",
            "manufacturer",
            "dosage_form",
            "application_method",
            "is_active",
        ]


def _selected_label(form, field_name):
    field = form.fields.get(field_name)
    if field is None or not hasattr(field, "queryset"):
        return ""
    raw = form.data.get(form.add_prefix(field_name)) if form.is_bound else form.initial.get(field_name)
    if not raw:
        raw = getattr(form.instance, f"{field_name}_id", None)
    try:
        selected = field.queryset.filter(pk=raw).first() if raw else None
    except (AttributeError, TypeError, ValueError):
        selected = None
    return str(selected or "")
