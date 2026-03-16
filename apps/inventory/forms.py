from django import forms

from .models import MedicalDevice


class MedicalDeviceForm(forms.ModelForm):
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
