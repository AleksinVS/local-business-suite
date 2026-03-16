from django import forms

from .models import WorkOrder, WorkOrderAttachment, WorkOrderComment


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
