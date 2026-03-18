import json

from django import forms
from django.conf import settings

from .json_utils import pretty_json, validate_role_rules_payload
from .models import Department


class DepartmentParentChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.indented_name


class DepartmentForm(forms.ModelForm):
    parent = DepartmentParentChoiceField(
        queryset=Department.objects.select_related("parent").order_by("parent_id", "name", "id"),
        required=False,
    )

    class Meta:
        model = Department
        fields = ["name", "parent"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            excluded_ids = set(self.instance.descendant_ids())
            self.fields["parent"].queryset = self.fields["parent"].queryset.exclude(pk__in=excluded_ids)


class RoleRulesForm(forms.Form):
    rules_json = forms.CharField(
        label="Конфигурация ролей",
        widget=forms.Textarea(attrs={"rows": 28, "spellcheck": "false"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["rules_json"] = settings.LOCAL_BUSINESS_ROLE_RULES_FILE.read_text(encoding="utf-8")

    def clean_rules_json(self):
        raw = self.cleaned_data["rules_json"]
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"Некорректный JSON: {exc.msg}.") from exc
        validate_role_rules_payload(payload)
        self.cleaned_data["rules_payload"] = payload
        return pretty_json(payload)
