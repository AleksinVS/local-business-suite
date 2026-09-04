import json

from django import forms

from .contract_store import get_contract
from .json_utils import pretty_json
from apps.workorders.contracts import validate_role_rules_payload
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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            from apps.workorders.selectors import visible_departments_queryset

            self.fields["parent"].queryset = visible_departments_queryset(user)
        if self.instance.pk:
            excluded_ids = set(self.instance.descendant_ids())
            self.fields["parent"].queryset = self.fields["parent"].queryset.exclude(pk__in=excluded_ids)
        raw_parent = self.data.get(self.add_prefix("parent")) if self.is_bound else self.initial.get("parent")
        if not raw_parent:
            raw_parent = getattr(self.instance, "parent_id", None)
        selected = self.fields["parent"].queryset.filter(pk=raw_parent).first() if raw_parent else None
        self.selected_parent_label = selected.indented_name if selected else ""


class RoleRulesForm(forms.Form):
    rules_json = forms.CharField(
        label="Конфигурация ролей",
        widget=forms.Textarea(attrs={"rows": 28, "spellcheck": "false"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["rules_json"] = pretty_json(get_contract("role_rules"))

    def clean_rules_json(self):
        raw = self.cleaned_data["rules_json"]
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f"Некорректный JSON: {exc.msg}.") from exc
        validate_role_rules_payload(
            payload,
            workflow_payload=get_contract("workflow_rules"),
        )
        self.cleaned_data["rules_payload"] = payload
        return pretty_json(payload)
