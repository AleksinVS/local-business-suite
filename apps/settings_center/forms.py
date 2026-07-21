from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.accounts.models import ExternalIdentity
from apps.core.models import Department


class ContractPayloadForm(forms.Form):
    payload = forms.CharField(
        label="JSON-содержимое",
        widget=forms.Textarea(attrs={"rows": 24, "spellcheck": "false"}),
    )
    confirm = forms.BooleanField(label="Подтверждаю применение изменения", required=False)


class EnvProposalForm(forms.Form):
    target_label = forms.CharField(label="Метка окружения", max_length=120, initial="default")
    key = forms.CharField(label="Ключ", max_length=120)
    value = forms.CharField(label="Значение", widget=forms.PasswordInput(render_value=True), required=False)


class HelpQuestionForm(forms.Form):
    question = forms.CharField(label="Вопрос", widget=forms.TextInput(), required=False)


class PortalUserCreateForm(forms.ModelForm):
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput, required=False)
    groups = forms.ModelMultipleChoiceField(label="Группы", queryset=Group.objects.order_by("name"), required=False)

    class Meta:
        model = get_user_model()
        fields = ["username", "first_name", "last_name", "email", "department", "is_active", "is_staff", "is_superuser", "groups"]

    department = forms.ModelChoiceField(
        label="Подразделение",
        queryset=Department.objects.order_by("parent_id", "name"),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {
            "username": "Логин",
            "first_name": "Имя",
            "last_name": "Фамилия",
            "email": "Email",
            "is_active": "Активен",
            "is_staff": "Доступ к администрированию",
            "is_superuser": "Суперпользователь",
        }
        for field_name, label in labels.items():
            if field_name in self.fields:
                self.fields[field_name].label = label


class PortalUserUpdateForm(PortalUserCreateForm):
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput, required=False)


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {
            "provider": "Поставщик",
            "subject_id": "Идентификатор субъекта",
            "username": "Логин",
            "upn": "UPN",
            "distinguished_name": "Distinguished name",
            "domain": "Домен",
            "sync_status": "Статус синхронизации",
        }
        for field_name, label in labels.items():
            if field_name in self.fields:
                self.fields[field_name].label = label
