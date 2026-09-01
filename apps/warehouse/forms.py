from django import forms
from django.forms import inlineformset_factory

from apps.core.models import Department
from apps.warehouse.models import (
    FundingSource,
    StockDocument,
    StockDocumentLine,
    StockLot,
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
    def __init__(self, *args, actor=None, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        if department is not None:
            warehouses = Warehouse.objects.filter(department=department)
        else:
            department_qs = _department_queryset(
                actor, WAREHOUSE_OPERATE_SCOPE, WAREHOUSE_ADJUST_SCOPE
            )
            warehouses = Warehouse.objects.filter(department__in=department_qs)
        locations = StorageLocation.objects.filter(warehouse__in=warehouses)
        self.fields["source_location"].queryset = locations
        self.fields["destination_location"].queryset = locations
        self.fields["item"].queryset = WarehouseItem.objects.filter(is_active=True)
        self.fields["lot"].queryset = StockLot.objects.filter(item__is_active=True)
        self.fields["funding_source"].queryset = FundingSource.objects.filter(is_active=True)

    class Meta:
        model = StockDocumentLine
        fields = [
            "sequence",
            "item",
            "lot",
            "funding_source",
            "quantity",
            "source_location",
            "destination_location",
            "fefo_override_reason",
        ]


class StockLotRegistrationForm(forms.ModelForm):
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        label="Подразделение регистрации",
        help_text="Используется для проверки прав и записи аудита; партия остаётся общей.",
    )

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = _department_queryset(
            actor, WAREHOUSE_OPERATE_SCOPE
        )
        self.fields["item"].queryset = WarehouseItem.objects.filter(is_active=True)

    class Meta:
        model = StockLot
        fields = [
            "department",
            "item",
            "batch_number",
            "expires_on",
            "incomplete_reason",
        ]
        widgets = {"expires_on": forms.DateInput(attrs={"type": "date"})}


StockDocumentLineFormSet = inlineformset_factory(
    StockDocument,
    StockDocumentLine,
    form=StockDocumentLineForm,
    extra=1,
    can_delete=True,
)


class WarehouseForm(forms.ModelForm):
    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = _department_queryset(
            actor, WAREHOUSE_MANAGE_LOCATIONS_SCOPE
        )

    class Meta:
        model = Warehouse
        fields = ["department", "code", "name", "is_active"]


class StorageLocationForm(forms.ModelForm):
    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = manageable_location_warehouses_queryset(actor)

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
    class Meta:
        model = WarehouseItemCategory
        fields = ["code", "name", "is_active"]


class UnitOfMeasureForm(forms.ModelForm):
    class Meta:
        model = UnitOfMeasure
        fields = ["code", "name", "quantity_precision", "is_active"]


class FundingSourceForm(forms.ModelForm):
    class Meta:
        model = FundingSource
        fields = ["code", "name", "is_active"]


class WarehouseItemForm(forms.ModelForm):
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
