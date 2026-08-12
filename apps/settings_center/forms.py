from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.accounts.department_policy import available_user_departments
from apps.accounts.models import ExternalIdentity
from apps.accounts.selectors import contract_role_names, selected_role_names_for_user
from apps.accounts.services import assignable_role_names_for_actor


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


class GroupWithProfileChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        profile = getattr(obj, "profile", None)
        title = getattr(profile, "title", "") if profile else ""
        if not title:
            return obj.name
        description = getattr(profile, "description", "") or ""
        if len(description) > 100:
            description = description[:100].rstrip() + "…"
        if description:
            return f"{title} ({obj.name}) — {description}"
        return f"{title} ({obj.name})"


class PortalUserCreateForm(forms.ModelForm):
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput, required=False)

    class Meta:
        model = get_user_model()
        fields = ["username", "first_name", "last_name", "email", "department", "is_active"]

    department = forms.ModelChoiceField(
        label="Подразделение",
        queryset=available_user_departments(),
        required=True,
        empty_label="Выберите подразделение",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {
            "username": "Логин",
            "first_name": "Имя",
            "last_name": "Фамилия",
            "email": "Email",
            "is_active": "Активен",
        }
        for field_name, label in labels.items():
            if field_name in self.fields:
                self.fields[field_name].label = label


class PortalUserProfileUpdateForm(PortalUserCreateForm):
    """Профиль пользователя без ролей и технических флагов доступа."""


class PortalUserUpdateForm(forms.Form):
    roles = GroupWithProfileChoiceField(
        label="Роли доступа",
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Можно назначать только роли из контракта. Технические группы сохраняются без изменений.",
    )
    is_superuser = forms.BooleanField(
        label="Супер-пользователь",
        required=False,
        help_text="Неограниченные права в портале. Доступно для изменения только суперпользователю.",
    )
    is_staff = forms.BooleanField(
        label="Доступ к администрированию",
        required=False,
        help_text="Разрешает вход в раздел администрирования Django при наличии нужных прав.",
    )
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)
    confirm_risk = forms.BooleanField(
        label="Подтверждаю выдачу рискованного доступа",
        required=False,
    )

    def __init__(self, *args, portal_user=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        role_names = contract_role_names()
        current_role_names = set()
        if portal_user is not None and actor is not None:
            current_role_names = set(selected_role_names_for_user(portal_user))
            role_names = assignable_role_names_for_actor(actor=actor, target_user=portal_user)
        self.fields["roles"].queryset = Group.objects.filter(name__in=role_names).select_related("profile").order_by("name")
        if portal_user is not None and not self.is_bound:
            self.initial["roles"] = list(portal_user.groups.filter(name__in=role_names).values_list("pk", flat=True))
        protected_role_names = current_role_names - set(role_names)
        self.protected_role_groups = list(
            Group.objects.filter(name__in=protected_role_names)
            .select_related("profile")
            .order_by("name")
        )
        self._protected_role_names = protected_role_names
        if protected_role_names:
            self.fields["roles"].help_text += (
                " Роли вне ваших полномочий показаны отдельно и сохраняются без изменений."
            )
        if portal_user is not None:
            self.initial["is_staff"] = portal_user.is_staff
            self.initial["is_superuser"] = portal_user.is_superuser
        self.can_manage_privileged_flags = bool(actor and actor.is_superuser)
        if not self.can_manage_privileged_flags:
            self.fields["is_staff"].disabled = True
            self.fields["is_superuser"].disabled = True

    def clean(self):
        cleaned_data = super().clean()
        selected_roles = cleaned_data.get("roles")
        if selected_roles is not None and self._protected_role_names:
            selected_names = set(selected_roles.values_list("name", flat=True))
            cleaned_data["roles"] = Group.objects.filter(
                name__in=selected_names | self._protected_role_names
            )
        if cleaned_data.get("is_superuser") and not cleaned_data.get("is_staff"):
            self.add_error(
                "is_staff",
                "Для супер-пользователя необходимо включить доступ к администрированию.",
            )
        return cleaned_data


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
