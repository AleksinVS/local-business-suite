from django import forms

from .models import (
    ATTACHMENT_ALLOWED_TYPES,
    ATTACHMENT_MAX_SIZE,
    KanbanColumnConfig,
    WorkOrder,
    WorkOrderAttachment,
    WorkOrderComment,
)


class WorkOrderForm(forms.ModelForm):
    class Meta:
        model = WorkOrder
        fields = [
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


class WorkOrderUpdateForm(forms.ModelForm):
    class Meta:
        model = WorkOrder
        fields = [
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
        fields = ["title"]
