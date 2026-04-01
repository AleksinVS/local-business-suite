import re

from django import forms

from .models import SERVICE_CHOICES, WaitingListEntry, WaitingListStatus


class WaitingListEntryForm(forms.ModelForm):
    """Form for creating and updating waiting list entries."""

    class Meta:
        model = WaitingListEntry
        fields = [
            "patient_name",
            "patient_dob",
            "patient_phone",
            "service_id",
            "date_tag",
            "date_end",
            "priority_cito",
            "comment",
        ]
        widgets = {
            "patient_dob": forms.TextInput(
                attrs={"placeholder": "ДД.ММ.ГГГГ", "maxlength": "10"}
            ),
            "patient_phone": forms.TextInput(
                attrs={"placeholder": "+7 (___) ___-__-__", "maxlength": "20"}
            ),
            "date_tag": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            ),
            "date_end": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            ),
            "comment": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date_tag"].required = False
        self.fields["date_end"].required = False
        self.fields["comment"].required = False

    def clean_patient_name(self):
        patient_name = self.cleaned_data.get("patient_name", "").strip()
        if len(patient_name) < 2:
            raise forms.ValidationError("ФИО пациента обязательно (минимум 2 символа).")
        return patient_name

    def clean_patient_dob(self):
        dob = self.cleaned_data.get("patient_dob", "")
        pattern = r"^\d{2}\.\d{2}\.\d{4}$"
        if not re.match(pattern, dob):
            raise forms.ValidationError(
                "Неверный формат даты рождения. Используйте ДД.ММ.ГГГГ."
            )
        return dob

    def clean_patient_phone(self):
        phone = self.cleaned_data.get("patient_phone", "")
        cleaned = re.sub(r"[^\d]", "", phone)
        if len(cleaned) != 11 or not cleaned.startswith(("7", "8")):
            raise forms.ValidationError(
                "Неверный формат телефона. Используйте +7 (XXX) XXX-XX-XX."
            )
        return phone


class WaitingListStatusForm(forms.ModelForm):
    """Form for quick status transitions."""

    status = forms.ChoiceField(choices=WaitingListStatus.choices)

    class Meta:
        model = WaitingListEntry
        fields = ["status"]
