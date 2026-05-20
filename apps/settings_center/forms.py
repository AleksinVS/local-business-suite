from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.accounts.models import ExternalIdentity
from apps.core.models import Department


class ContractPayloadForm(forms.Form):
    payload = forms.CharField(widget=forms.Textarea(attrs={"rows": 24, "spellcheck": "false"}))
    confirm = forms.BooleanField(required=False)


class EnvProposalForm(forms.Form):
    target_label = forms.CharField(max_length=120, initial="default")
    key = forms.CharField(max_length=120)
    value = forms.CharField(widget=forms.PasswordInput(render_value=True), required=False)


class HelpQuestionForm(forms.Form):
    question = forms.CharField(widget=forms.TextInput(), required=False)


class PortalUserCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False)
    groups = forms.ModelMultipleChoiceField(queryset=Group.objects.order_by("name"), required=False)

    class Meta:
        model = get_user_model()
        fields = ["username", "first_name", "last_name", "email", "department", "is_active", "is_staff", "is_superuser", "groups"]

    department = forms.ModelChoiceField(queryset=Department.objects.order_by("parent_id", "name"), required=False)


class PortalUserUpdateForm(PortalUserCreateForm):
    password = forms.CharField(widget=forms.PasswordInput, required=False)


class ExternalIdentityForm(forms.ModelForm):
    class Meta:
        model = ExternalIdentity
        fields = [
            "provider",
            "subject_id",
            "username",
            "upn",
            "distinguished_name",
            "domain",
            "sync_status",
        ]
