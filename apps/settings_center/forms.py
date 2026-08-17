from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError

from apps.accounts.department_policy import available_user_departments
from apps.accounts.models import ExternalIdentity
from apps.accounts.selectors import contract_role_names, selected_role_names_for_user
from apps.accounts.services import assignable_role_names_for_actor
from apps.core.contract_store import get_contract


class ContractPayloadForm(forms.Form):
    payload = forms.CharField(
        label="JSON-содержимое",
        widget=forms.Textarea(attrs={"rows": 24, "spellcheck": "false"}),
    )
    confirm = forms.BooleanField(label="Подтверждаю применение изменения", required=False)
    base_hash = forms.CharField(widget=forms.HiddenInput, required=True)


class RoleDefinitionForm(forms.Form):
    display_name = forms.CharField(label="Название роли", max_length=150, required=False)
    description = forms.CharField(
        label="Описание роли",
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    base_hash = forms.CharField(widget=forms.HiddenInput)
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)
    risk_confirmed = forms.BooleanField(
        label="Подтверждаю изменение чувствительных прав",
        required=False,
    )
    active_group = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, role_read_model, **kwargs):
        super().__init__(*args, **kwargs)
        self.role_read_model = role_read_model
        self.capability_groups = []
        self.fields["display_name"].initial = role_read_model["label"]
        self.fields["description"].initial = role_read_model["description"]
        for section in role_read_model["sections"]:
            for capability in section["capabilities"]:
                code = capability["code"]
                field_name = f"capability__{code}"
                value = capability["value"]
                capability_type = capability["type"]
                if capability_type == "flag":
                    field = forms.BooleanField(required=False, label=capability["label"])
                elif capability_type == "scope":
                    from apps.workorders.contracts import capability_values
                    from apps.workorders.policies import SCOPE_LABELS

                    source = capability.get("values_source")
                    choices = capability_values(
                        source,
                        workflow_payload=get_contract("workflow_rules"),
                    )
                    field = forms.ChoiceField(
                        choices=[
                            (choice, SCOPE_LABELS.get(choice, {
                                "all": "Все записи",
                                "authored": "Только созданные пользователем",
                                "none": "Нет доступа",
                            }.get(choice, choice)))
                            for choice in choices
                        ],
                        label=capability["label"],
                    )
                elif capability_type == "targets":
                    from apps.workorders.contracts import capability_values
                    from apps.workorders.models import WorkOrderStatus
                    from apps.waiting_list.models import WaitingListStatus

                    source = capability.get("values_source")
                    values = capability_values(
                        source,
                        workflow_payload=get_contract("workflow_rules"),
                    )
                    status_labels = dict(WorkOrderStatus.choices)
                    status_labels.update(dict(WaitingListStatus.choices))
                    field = forms.MultipleChoiceField(
                        label=capability["label"],
                        choices=[("*", "Все статусы")] + [
                            (status, status_labels.get(status, status))
                            for status in values
                            if status != "*"
                        ],
                        widget=forms.CheckboxSelectMultiple,
                        required=False,
                        help_text=(
                            "Выберите отдельные статусы или вариант «Все статусы». "
                            "При выборе «Все статусы» остальные отметки не учитываются."
                        ),
                    )
                    value = ["*"] if value == "*" else list(value or [])
                else:
                    continue
                field.initial = value
                field.help_text = field.help_text or capability["description"]
                self.fields[field_name] = field
        for group in role_read_model.get("sections", []):
            self.capability_groups.append({
                "code": group["code"],
                "label": group["label"],
                "description": group.get("description", ""),
                "items": [
                    {
                        "field": self[f"capability__{capability['code']}"],
                        "capability": capability,
                    }
                    for capability in group["capabilities"]
                    if f"capability__{capability['code']}" in self.fields
                ],
            })
        group_codes = {group["code"] for group in self.capability_groups}
        requested_group = self.data.get("active_group", "") if self.is_bound else self.initial.get("active_group", "")
        self.initial["active_group"] = requested_group if requested_group in group_codes else (
            self.capability_groups[0]["code"] if self.capability_groups else ""
        )
        if self.is_bound:
            self.data = self.data.copy()
            self.data["active_group"] = self.initial["active_group"]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("capability__waiting_list_edit_scope") == "none":
            cleaned["capability__waiting_list_edit_statuses"] = []
        if cleaned.get("capability__waiting_list_transition_scope") == "none":
            cleaned["capability__waiting_list_transition_from_statuses"] = []
            cleaned["capability__waiting_list_transition_targets"] = []
        return cleaned

    def proposed_config(self):
        display_name = (
            self.cleaned_data.get("display_name", "")
            if self.is_bound and "display_name" in self.data
            else self.initial.get("display_name", self.role_read_model["label"])
        )
        description = (
            self.cleaned_data.get("description", "")
            if self.is_bound and "description" in self.data
            else self.initial.get("description", self.role_read_model["description"])
        )
        proposed = {
            "display_name": display_name,
            "description": description,
        }
        for section in self.role_read_model["sections"]:
            for capability in section["capabilities"]:
                code = capability["code"]
                field_name = f"capability__{code}"
                value = self.cleaned_data[field_name] if self.is_bound and field_name in self.cleaned_data else self.fields[field_name].initial
                if capability["type"] == "targets":
                    value = "*" if "*" in value else list(value)
                proposed[code] = value
        return proposed


class RoleDescriptionForm(forms.Form):
    description = forms.CharField(
        label="Описание роли",
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    base_hash = forms.CharField(widget=forms.HiddenInput)
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)
    risk_confirmed = forms.BooleanField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, role_read_model, **kwargs):
        super().__init__(*args, **kwargs)
        self.role_read_model = role_read_model
        self.fields["description"].initial = role_read_model["description"]

    def proposed_config(self):
        proposed = dict(self.role_read_model["config"])
        proposed["description"] = self.cleaned_data["description"]
        return proposed


class MemoryGroupMembershipForm(forms.Form):
    group_names = forms.MultipleChoiceField(
        label="Технические группы памяти",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    reason = forms.CharField(
        label="Причина",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)
    confirmed = forms.BooleanField(
        label="Подтверждаю изменение технических полномочий памяти",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.memory.access_services import memory_group_choices

        self.fields["group_names"].choices = [
            (item["code"], f"{item['label']} ({item['code']}) — {item['description']}")
            for item in memory_group_choices()
        ]


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


class AccessUserProfileForm(PortalUserProfileUpdateForm):
    reason = forms.CharField(
        label="Причина изменения",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)


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
    reason = forms.CharField(
        label="Причина изменения доступа",
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
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


class AccessUserStatusForm(forms.Form):
    """Small context editor; lifecycle rules remain in ``update_local_user``."""

    is_active = forms.BooleanField(label="Активная учетная запись", required=False)
    reason = forms.CharField(label="Причина", max_length=1000)
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)


class AccessUserDepartmentForm(forms.Form):
    department = forms.ModelChoiceField(
        label="Подразделение",
        queryset=available_user_departments(),
        required=True,
    )
    reason = forms.CharField(label="Причина", max_length=1000)
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)


class AccessExternalIdentityForm(ExternalIdentityForm):
    reason = forms.CharField(
        label="Причина изменения",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)


class AccessUserBundleForm(forms.Form):
    """Один черновик карточки пользователя с предметными группами полей."""

    username = forms.CharField(label="Логин", max_length=150)
    first_name = forms.CharField(label="Имя", max_length=150, required=False)
    last_name = forms.CharField(label="Фамилия", max_length=150, required=False)
    email = forms.EmailField(label="Email", required=False)
    department = forms.ModelChoiceField(
        label="Подразделение",
        queryset=available_user_departments(),
        required=True,
    )
    is_active = forms.BooleanField(label="Активная учетная запись", required=False)
    password = forms.CharField(
        label="Новый пароль",
        widget=forms.PasswordInput(render_value=True),
        required=False,
        help_text="Оставьте пустым, чтобы не менять пароль.",
    )
    ad_provider = forms.ChoiceField(label="Поставщик", choices=ExternalIdentity.Provider.choices)
    ad_subject_id = forms.CharField(label="Идентификатор субъекта", max_length=255, required=False)
    ad_username = forms.CharField(label="Логин AD", max_length=255, required=False)
    ad_upn = forms.CharField(label="UPN", max_length=255, required=False)
    ad_distinguished_name = forms.CharField(label="Distinguished name", required=False)
    ad_domain = forms.CharField(label="Домен", max_length=255, required=False)
    ad_sync_status = forms.ChoiceField(label="Статус синхронизации", choices=ExternalIdentity.SyncStatus.choices)
    roles = GroupWithProfileChoiceField(
        label="Должностные функции",
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Роли определяют рабочие функции; разделы сайта вычисляются из их возможностей.",
    )
    is_superuser = forms.BooleanField(label="Супер-пользователь", required=False)
    is_staff = forms.BooleanField(label="Доступ к Django Admin", required=False)
    memory_group_names = forms.MultipleChoiceField(
        label="Технические группы памяти",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    reason = forms.CharField(
        label="Причина всех изменений",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)
    confirm_risk = forms.BooleanField(
        label="Подтверждаю риск изменения привилегированного доступа",
        required=False,
    )
    confirm_memory = forms.BooleanField(
        label="Подтверждаю изменение технических полномочий памяти",
        required=False,
    )
    active_editor = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, portal_user, actor, ad_identity=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.portal_user = portal_user
        self.actor = actor
        role_names = assignable_role_names_for_actor(actor=actor, target_user=portal_user)
        current_role_names = set(selected_role_names_for_user(portal_user))
        self.fields["roles"].queryset = (
            Group.objects.filter(name__in=role_names)
            .select_related("profile")
            .order_by("name")
        )
        protected_role_names = current_role_names - set(role_names)
        self._protected_role_names = protected_role_names
        self.protected_role_groups = list(
            Group.objects.filter(name__in=protected_role_names)
            .select_related("profile")
            .order_by("name")
        )
        from apps.memory.access_services import memory_group_choices

        self.fields["memory_group_names"].choices = [
            (item["code"], f"{item['label']} ({item['code']}) — {item['description']}")
            for item in memory_group_choices()
        ]
        can_edit_account = bool(actor.is_active and actor.is_superuser)
        for name in (
            "username", "first_name", "last_name", "email", "department", "is_active",
            "password", "ad_provider", "ad_subject_id", "ad_username", "ad_upn",
            "ad_distinguished_name", "ad_domain", "ad_sync_status", "memory_group_names",
        ):
            self.fields[name].disabled = not can_edit_account
        self.fields["is_staff"].disabled = not can_edit_account
        self.fields["is_superuser"].disabled = not can_edit_account
        self.can_edit_account = can_edit_account
        identity = ad_identity
        self.initial.update({
                "username": portal_user.username,
                "first_name": portal_user.first_name,
                "last_name": portal_user.last_name,
                "email": portal_user.email,
                "department": portal_user.department_id,
                "is_active": portal_user.is_active,
                "ad_provider": getattr(identity, "provider", ExternalIdentity.Provider.ACTIVE_DIRECTORY),
                "ad_subject_id": getattr(identity, "subject_id", ""),
                "ad_username": getattr(identity, "username", ""),
                "ad_upn": getattr(identity, "upn", ""),
                "ad_distinguished_name": getattr(identity, "distinguished_name", ""),
                "ad_domain": getattr(identity, "domain", ""),
                "ad_sync_status": getattr(identity, "sync_status", ExternalIdentity.SyncStatus.MANUAL),
                "roles": list(portal_user.groups.filter(name__in=role_names).values_list("pk", flat=True)),
                "is_staff": portal_user.is_staff,
                "is_superuser": portal_user.is_superuser,
                "memory_group_names": list(
                    portal_user.groups.filter(
                        name__in=[choice[0] for choice in self.fields["memory_group_names"].choices]
                    ).values_list("name", flat=True)
                ),
            "active_editor": "roles",
        })

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
                "Для супер-пользователя необходимо включить доступ к Django Admin.",
            )
        return cleaned_data

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if username and get_user_model().objects.filter(username__iexact=username).exclude(
            pk=self.portal_user.pk
        ).exists():
            raise ValidationError("Пользователь с таким логином уже существует.")
        return username


class AccessRoleMembershipForm(forms.Form):
    selected_user_ids = forms.MultipleChoiceField(
        label="Пользователи роли",
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    reason = forms.CharField(label="Причина изменения состава", max_length=1000)
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)
    risk_confirmed = forms.BooleanField(
        label="Подтверждаю риск изменения состава роли",
        required=False,
    )

    def __init__(self, *args, role_name=None, **kwargs):
        super().__init__(*args, **kwargs)
        users = get_user_model().objects.order_by("username", "pk")
        self.fields["selected_user_ids"].choices = [
            (str(user.pk), user.get_full_name() or user.username) for user in users
        ]
        self.role_name = role_name or ""
