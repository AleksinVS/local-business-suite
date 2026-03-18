from django import forms

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
