from django import forms
from django.contrib.auth.models import Group

from apps.core.models import Department

from .models import (
    ATTACHMENT_ALLOWED_TYPES,
    ATTACHMENT_MAX_SIZE,
    Board,
    KanbanColumnConfig,
    WorkOrder,
    WorkOrderAttachment,
    WorkOrderComment,
)
from .selectors import (
    visible_boards_queryset,
    visible_departments_queryset,
    visible_devices_queryset,
)


class BoardRoleMultipleChoiceField(forms.MultipleChoiceField):
    """Статический список кодов ролей с понятными подписями из профиля группы."""


class BoardAccessForm(forms.Form):
    group_names = BoardRoleMultipleChoiceField(
        label="Роли, которым видна доска",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    reason = forms.CharField(
        label="Причина",
        required=True,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Обязательно: причина сохраняется в журнале изменения доступа.",
    )
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)
    risk_confirmed = forms.BooleanField(
        label="Подтверждаю изменение круга сотрудников с доступом к доске",
        required=False,
    )

    def __init__(self, *args, source="settings_center", **kwargs):
        super().__init__(*args, **kwargs)
        from .policies import board_access_role_names

        role_names = board_access_role_names()
        groups = {
            group.name: group
            for group in Group.objects.filter(name__in=role_names)
            .select_related("profile")
            .order_by("name")
        }
        choices = []
        for role_name in role_names:
            group = groups.get(role_name)
            profile = getattr(group, "profile", None) if group else None
            label = getattr(profile, "title", "") or role_name
            choices.append((role_name, f"{label} ({role_name})"))
        self.fields["group_names"].choices = choices
        if source == "django_admin_break_glass":
            self.fields["reason"].help_text = "Обязательно для резервного изменения."


class DepartmentChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.indented_name


def department_choice_label(department):
    return department.full_name


def device_choice_label(device):
    inventory_number = device.inventory_number or "не указан"
    return f"{device.name} · инв. № {inventory_number}"


class DeviceChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return device_choice_label(obj)


class WorkOrderForm(forms.ModelForm):
    department = DepartmentChoiceField(
        queryset=Department.objects.select_related("parent").order_by("parent_id", "name", "id")
    )
    device = DeviceChoiceField(queryset=visible_devices_queryset(None), required=False)

    class Meta:
        model = WorkOrder
        fields = [
            "board",
            "description",
            "department",
            "priority",
            "device",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["device"].required = False
        if user:
            self.fields["board"].queryset = visible_boards_queryset(user)
            self.fields["department"].queryset = visible_departments_queryset(user)
            self.fields["device"].queryset = visible_devices_queryset(user)
            # If only one board is visible, set it as initial
            if self.fields["board"].queryset.count() == 1:
                self.fields["board"].initial = self.fields["board"].queryset.first()

    def clean(self):
        cleaned_data = super().clean()
        department = cleaned_data.get("department")
        device = cleaned_data.get("device")
        if device and department and device.department_id != department.id:
            self.add_error(
                "department",
                "Выберите подразделение, к которому относится медицинское изделие.",
            )
        return cleaned_data


class WorkOrderUpdateForm(forms.ModelForm):
    department = DepartmentChoiceField(
        queryset=Department.objects.select_related("parent").order_by("parent_id", "name", "id")
    )

    class Meta:
        model = WorkOrder
        fields = [
            "board",
            "title",
            "description",
            "department",
            "priority",
            "device",
            "assignee",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["device"].required = False
        if user:
            self.fields["board"].queryset = visible_boards_queryset(user)
            self.fields["department"].queryset = visible_departments_queryset(user)
            preserved_device_ids = (
                (self.instance.device_id,)
                if self.instance and self.instance.pk and self.instance.device_id
                else ()
            )
            self.fields["device"].queryset = visible_devices_queryset(
                user,
                include_archived_ids=preserved_device_ids,
            )


class WorkOrderCommentForm(forms.ModelForm):
    class Meta:
        model = WorkOrderComment
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 3, "placeholder": "Комментарий"}),
        }


class WorkOrderAttachmentForm(forms.ModelForm):
    class Meta:
        model = WorkOrderAttachment
        fields = ["file"]

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        content_type = getattr(uploaded_file, "content_type", "")
        if uploaded_file.size > ATTACHMENT_MAX_SIZE:
            raise forms.ValidationError("Файл превышает 10 МБ.")
        if content_type not in ATTACHMENT_ALLOWED_TYPES:
            raise forms.ValidationError("Недопустимый тип файла.")
        return uploaded_file


class WorkOrderRatingForm(forms.ModelForm):
    class Meta:
        model = WorkOrder
        fields = ["rating"]
        widgets = {
            "rating": forms.NumberInput(attrs={"min": 1, "max": 5}),
        }


class KanbanColumnTitleForm(forms.ModelForm):
    class Meta:
        model = KanbanColumnConfig
        fields = ["title", "wip_limit"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["wip_limit"].required = False

    def clean_wip_limit(self):
        value = self.cleaned_data.get("wip_limit")
        if value in (None, "") and self.instance and self.instance.pk:
            return self.instance.wip_limit
        return value or 0
