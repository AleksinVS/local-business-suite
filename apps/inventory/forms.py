from django import forms

from apps.core.models import Department

from .models import MedicalDevice


class DepartmentChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.indented_name


class MedicalDeviceForm(forms.ModelForm):
    department = DepartmentChoiceField(
        queryset=Department.objects.select_related("parent").order_by("parent_id", "name", "id")
    )

    class Meta:
        model = MedicalDevice
        fields = [
            "name",
            "manufacturer",
            "model",
            "serial_number",
            "inventory_number",
            "department",
            "location",
            "operational_status",
            "commissioned_at",
            "notes",
        ]
        widgets = {
            "commissioned_at": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }
