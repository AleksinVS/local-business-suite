from django import forms

from apps.core.models import Department

from .models import MedicalDevice


# Имя подразделения-агрегатора. Должно совпадать с CATCHALL_DEPARTMENT_NAME
# в import_frmo_devices и с data-миграцией 0007_catchall_department.
CATCHALL_DEPARTMENT_NAME = "Вологодская областная больница №3"


class DepartmentChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        label = obj.indented_name
        if obj.name == CATCHALL_DEPARTMENT_NAME and obj.parent_id is None:
            return f"{label}  (агрегатор)"
        return label


class MedicalDeviceForm(forms.ModelForm):
    department = DepartmentChoiceField(
        queryset=Department.objects.select_related("parent").order_by("parent_id", "name", "id")
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Агрегатор показываем первым в списке и подставляем по умолчанию
        # при создании нового изделия. На существующей записи initial не
        # перетирает уже выбранное подразделение.
        catchall = (
            Department.objects.filter(
                parent=None, name=CATCHALL_DEPARTMENT_NAME
            )
            .order_by("id")
            .first()
        )
        if catchall is None:
            return

        # Переупорядочиваем queryset: сначала агрегатор, затем остальные
        # в порядке иерархии (parent_id, name, id).
        others = Department.objects.exclude(pk=catchall.pk).select_related(
            "parent"
        ).order_by("parent_id", "name", "id")
        self.fields["department"].queryset = Department.objects.order_by(
            "pk"
        ).filter(pk=catchall.pk) | others

        if not self.instance.pk or not self.instance.department_id:
            self.fields["department"].initial = catchall.pk

    class Meta:
        model = MedicalDevice
        fields = [
            "name",
            "device_type",
            "manufacturer",
            "production_country",
            "model",
            "serial_number",
            "inventory_number",
            "registration_date",
            "registration_certificate_number",
            "production_date",
            "commissioned_at",
            "service_life_years",
            "department",
            "address",
            "location",
            "operational_status",
            "decommissioned_at",
            "decommission_reason",
            "notes",
        ]
        widgets = {
            "registration_date": forms.DateInput(attrs={"type": "date"}),
            "production_date": forms.DateInput(attrs={"type": "date"}),
            "commissioned_at": forms.DateInput(attrs={"type": "date"}),
            "decommissioned_at": forms.DateInput(attrs={"type": "date"}),
            "address": forms.Textarea(attrs={"rows": 2}),
            "decommission_reason": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }