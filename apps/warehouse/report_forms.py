from __future__ import annotations

from datetime import date

from django import forms

from apps.core.models import Department
from apps.warehouse.policies import WAREHOUSE_VIEW_SCOPE, department_ids_for_warehouse_scope


class WarehouseReportFilterForm(forms.Form):
    """Shared visible filter contract for all warehouse reports."""

    search = forms.CharField(label="Поиск", required=False)
    department_id = forms.IntegerField(label="Подразделение", required=False)
    warehouse = forms.CharField(label="Склад", required=False)
    location = forms.CharField(label="Адрес", required=False)
    expiry_state = forms.ChoiceField(
        label="Срок годности", required=False,
        choices=[("", "Все"), ("expired", "Просрочено"), ("warning", "Истекает скоро"), ("valid", "Годен"), ("none", "Без срока")],
    )
    location_purpose = forms.ChoiceField(
        label="Состояние адреса", required=False,
        choices=[("", "Все состояния"), ("available", "Доступно"), ("quarantine", "Карантин"), ("unassigned", "Адрес не назначен")],
    )

    def __init__(self, *args, actor=None, period=False, **kwargs):
        configured_thresholds = kwargs.pop("expiry_warning_days", None)
        super().__init__(*args, **kwargs)
        self.actor = actor
        if period:
            # Expense rows have no warehouse, location or expiry dimensions.
            for field_name in ("warehouse", "location", "expiry_state", "location_purpose"):
                self.fields.pop(field_name, None)
        else:
            thresholds = sorted({int(value) for value in (configured_thresholds or (30, 90, 180)) if int(value) > 0})
            choices = [("", "Все"), ("expired", "Просрочено")]
            lower = 0
            for threshold in thresholds:
                choices.append((f"due_{threshold}", f"Истекает через {threshold} дней" if lower == 0 else f"Истекает через {lower + 1}–{threshold} дней"))
                lower = threshold
            choices.append(("valid", f"Годен более {lower} дней" if lower else "Годен"))
            choices.append(("none", "Без срока"))
            self.fields["expiry_state"].choices = choices
        ids = department_ids_for_warehouse_scope(actor, WAREHOUSE_VIEW_SCOPE)
        department_queryset = Department.objects.all() if ids is None else Department.objects.filter(pk__in=ids)
        # The visible control is the shared bounded autocomplete.  Do not
        # materialize the department catalogue into a hidden native select.
        self.fields["department_id"].widget = forms.HiddenInput()
        raw_department = self.data.get(self.add_prefix("department_id")) if self.is_bound else self.initial.get("department_id")
        if raw_department and hasattr(department_queryset, "filter"):
            selected = department_queryset.filter(pk=raw_department).first()
        elif raw_department:
            selected = next(
                (
                    department
                    for department in department_queryset
                    if str(getattr(department, "pk", "")) == str(raw_department)
                ),
                None,
            )
        else:
            selected = None
        self.selected_department_label = selected.name if selected else ""
        if period:
            self.fields["start"] = forms.DateField(label="С даты", required=False, widget=forms.DateInput(attrs={"type": "date"}))
            self.fields["end"] = forms.DateField(label="По дату", required=False, widget=forms.DateInput(attrs={"type": "date"}))
        else:
            self.fields["as_of"] = forms.DateField(label="На дату", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        if "start" in cleaned and cleaned.get("start") and cleaned.get("end") and cleaned["start"] > cleaned["end"]:
            self.add_error("end", "Дата окончания не может быть раньше даты начала.")
        department_id = cleaned.get("department_id")
        ids = department_ids_for_warehouse_scope(self.actor, WAREHOUSE_VIEW_SCOPE)
        if department_id and ids is not None and department_id not in ids:
            self.add_error("department_id", "Подразделение недоступно.")
        return cleaned


def filter_report_rows(rows, cleaned_data, *, expiry_warning_days=(90,)):
    """Apply the same row filters to HTML, CSV and XLSX callers."""
    search = (cleaned_data.get("search") or "").casefold()
    department_id = cleaned_data.get("department_id")
    warehouse = (cleaned_data.get("warehouse") or "").casefold()
    location = (cleaned_data.get("location") or "").casefold()
    state = cleaned_data.get("expiry_state")
    location_purpose = cleaned_data.get("location_purpose")
    today = cleaned_data.get("as_of") or date.today()
    result = []
    for row in rows:
        if department_id and row.get("department_id") != department_id:
            continue
        if warehouse and warehouse not in str(row.get("warehouse", "")).casefold():
            continue
        if location and location not in str(row.get("location", "")).casefold():
            continue
        if location_purpose and row.get("location_purpose", "available") != location_purpose:
            continue
        if search and search not in " ".join(str(row.get(key, "")) for key in ("item", "series", "funding_source", "department")).casefold():
            continue
        expires = row.get("expires_on")
        days = (expires - today).days if expires else None
        thresholds = sorted({int(value) for value in (expiry_warning_days or (90,)) if int(value) > 0})
        if expires is None:
            actual_state = "none"
        elif days < 0:
            actual_state = "expired"
        else:
            actual_state = "valid"
            lower = 0
            for threshold in thresholds:
                if days <= threshold:
                    actual_state = f"due_{threshold}"
                    break
                lower = threshold
        if state == "warning":
            actual_state = "warning" if expires is not None and days >= 0 and days <= max(thresholds or [90]) else actual_state
        if state and state != actual_state:
            continue
        result.append(row)
    return result
