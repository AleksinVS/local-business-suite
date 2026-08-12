from __future__ import annotations

import hashlib
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils.crypto import salted_hmac
from django.utils import timezone

from apps.core.contract_store import current_contract_hash
from apps.core.file_locks import (
    FileLockTimeoutError,
    access_control_write_lock_path,
    exclusive_file_lock,
)
from apps.workorders.policies import can_manage_roles

from .department_policy import available_user_departments
from .models import AccessAssignmentAudit, ExternalIdentity
from .selectors import (
    access_assignment_consequences,
    capability_catalog,
    contract_role_configs,
    role_assignment_allowlist,
    role_risk_markers,
    selected_role_names_for_user,
)


SAFE_AD_ATTRIBUTE_KEYS = {
    "displayName",
    "givenName",
    "mail",
    "memberOf",
    "objectSid",
    "sAMAccountName",
    "sn",
    "userPrincipalName",
}

ACCESS_PREVIEW_SIGNING_SALT = "accounts.access-assignment-preview.v2"
ACCESS_PREVIEW_MAX_AGE_SECONDS = 600

PRIVILEGED_FLAG_LABELS = {
    "is_staff": "Доступ к администрированию",
    "is_superuser": "Супер-пользователь",
}

SELF_ASSIGNMENT_RISK_MARKER = (
    "Самоназначение роли суперпользователем: роль сохранится после возможного снятия "
    "технического флага суперпользователя"
)
BREAK_GLASS_RISK_MARKER = "Резервное изменение доступа через Django Admin"


def assignable_role_names_for_actor(*, actor, target_user):
    """Роли, которые UI может предложить, не заменяя серверную apply-проверку."""

    current_actor = _current_access_actor(actor)
    _require_role_manager(current_actor)
    if current_actor.is_superuser:
        return tuple(contract_role_configs())
    if current_actor.pk == target_user.pk:
        return ()
    allowlist = role_assignment_allowlist()
    allowed = {
        target_role
        for actor_role in selected_role_names_for_user(current_actor)
        for target_role in allowlist.get(actor_role, ())
    }
    return tuple(sorted(allowed))


def preview_role_assignment(
    *,
    actor,
    target_user,
    selected_role_names,
    is_staff=None,
    is_superuser=None,
    source=AccessAssignmentAudit.Source.SETTINGS_CENTER,
    reason="",
):
    """Строит канонический diff и подписывает его для последующего применения."""

    actor = _current_access_actor(actor)
    _require_role_manager(actor)
    source, reason, is_break_glass = _validate_assignment_context(
        actor=actor,
        source=source,
        reason=reason,
    )
    after = _validate_role_names(selected_role_names)
    before = selected_role_names_for_user(target_user)
    _validate_role_assignment_authority(
        actor=actor,
        target_user=target_user,
        before=before,
        after=after,
    )
    flags_before = _technical_flags_for_user(target_user)
    flags_after = _requested_technical_flags(
        target_user,
        is_staff=is_staff,
        is_superuser=is_superuser,
    )
    _validate_technical_flag_change(
        actor=actor,
        target_user=target_user,
        before=flags_before,
        after=flags_after,
    )
    configs = contract_role_configs()
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    risk_markers = [
        marker
        for role_name in added
        for marker in role_risk_markers(role_name, configs[role_name])
    ]
    risk_markers.extend(_technical_flag_risk_markers(flags_before, flags_after))
    risk_markers.extend(
        _assignment_context_risk_markers(
            actor=actor,
            target_user=target_user,
            before=before,
            after=after,
            is_break_glass=is_break_glass,
        )
    )
    flags_changed = _technical_flag_changes(flags_before, flags_after)
    payload = {
        "actor_id": actor.pk,
        "target_id": target_user.pk,
        "before": before,
        "after": after,
        "flags_before": flags_before,
        "flags_after": flags_after,
        "actor_state": _actor_access_state(actor),
        "role_contract_hash": current_contract_hash("role_rules"),
        "source": source,
        "reason": reason,
        "is_break_glass": is_break_glass,
        "nonce": str(uuid.uuid4()),
    }
    return {
        "before": before,
        "after": after,
        "added": added,
        "removed": removed,
        "flags_before": flags_before,
        "flags_after": flags_after,
        "flags_changed": flags_changed,
        "risk_markers": risk_markers,
        "requires_confirmation": bool(risk_markers),
        "source": source,
        "is_break_glass": is_break_glass,
        "consequences": access_assignment_consequences(before, after),
        "preview_token": signing.dumps(payload, salt=ACCESS_PREVIEW_SIGNING_SALT, compress=True),
    }


def apply_role_assignment(
    *,
    actor,
    target_user,
    selected_role_names,
    preview_token,
    risk_confirmed=False,
    is_staff=None,
    is_superuser=None,
    source=AccessAssignmentAudit.Source.SETTINGS_CENTER,
    reason="",
):
    """Сериализовать назначение с записью и предпросмотром контракта ролей."""
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            return _apply_role_assignment_locked(
                actor=actor,
                target_user=target_user,
                selected_role_names=selected_role_names,
                preview_token=preview_token,
                risk_confirmed=risk_confirmed,
                is_staff=is_staff,
                is_superuser=is_superuser,
                source=source,
                reason=reason,
            )
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


@transaction.atomic
def _apply_role_assignment_locked(
    *,
    actor,
    target_user,
    selected_role_names,
    preview_token,
    risk_confirmed=False,
    is_staff=None,
    is_superuser=None,
    source=AccessAssignmentAudit.Source.SETTINGS_CENTER,
    reason="",
):
    """Меняет контрактные роли и технические флаги в одной транзакции."""

    after = _validate_role_names(selected_role_names)
    signed_preview = _load_preview_token(preview_token)
    if signed_preview.get("actor_id") != actor.pk or signed_preview.get("target_id") != target_user.pk:
        raise ValidationError("Предпросмотр относится к другому пользователю или администратору.")
    if signed_preview.get("after") != after:
        raise ValidationError("Выбранные роли изменились после предпросмотра. Выполните предпросмотр снова.")
    User = get_user_model()
    locked_actor = User.objects.select_for_update().get(pk=actor.pk)
    _require_role_manager(locked_actor)
    source, reason, is_break_glass = _validate_assignment_context(
        actor=locked_actor,
        source=source,
        reason=reason,
    )
    if signed_preview.get("source") != source or signed_preview.get("reason") != reason:
        raise ValidationError("Источник или причина изменились после предпросмотра.")
    if signed_preview.get("is_break_glass") is not is_break_glass:
        raise ValidationError("Контекст резервного изменения не совпадает с предпросмотром.")
    if signed_preview.get("actor_state") != _actor_access_state(locked_actor):
        raise ValidationError("Права администратора изменились после предпросмотра. Повторите проверку.")
    if signed_preview.get("role_contract_hash") != current_contract_hash("role_rules"):
        raise ValidationError("Контракт ролей изменился после предпросмотра. Повторите проверку.")

    locked_target = (
        locked_actor
        if target_user.pk == locked_actor.pk
        else User.objects.select_for_update().get(pk=target_user.pk)
    )
    flags_after = _requested_technical_flags(
        locked_target,
        is_staff=is_staff,
        is_superuser=is_superuser,
    )
    if signed_preview.get("flags_after") != flags_after:
        raise ValidationError("Технические флаги изменились после предпросмотра. Выполните предпросмотр снова.")
    before = selected_role_names_for_user(locked_target)
    flags_before = _technical_flags_for_user(locked_target)
    if signed_preview.get("before") != before:
        raise ValidationError("Роли пользователя уже изменены. Выполните предпросмотр снова.")
    if signed_preview.get("flags_before") != flags_before:
        raise ValidationError("Технические флаги пользователя уже изменены. Выполните предпросмотр снова.")
    _validate_role_assignment_authority(
        actor=locked_actor,
        target_user=locked_target,
        before=before,
        after=after,
    )
    _validate_technical_flag_change(
        actor=locked_actor,
        target_user=locked_target,
        before=flags_before,
        after=flags_after,
    )

    configs = contract_role_configs()
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    risk_markers = [
        marker
        for role_name in added
        for marker in role_risk_markers(role_name, configs[role_name])
    ]
    risk_markers.extend(_technical_flag_risk_markers(flags_before, flags_after))
    risk_markers.extend(
        _assignment_context_risk_markers(
            actor=locked_actor,
            target_user=locked_target,
            before=before,
            after=after,
            is_break_glass=is_break_glass,
        )
    )
    if risk_markers and not risk_confirmed:
        raise ValidationError("Изменение чувствительного доступа требует явного подтверждения.")

    selected_groups = list(Group.objects.filter(name__in=after).order_by("name"))
    selected_group_names = {group.name for group in selected_groups}
    missing_groups = sorted(set(after) - selected_group_names)
    if missing_groups:
        raise ValidationError(
            "Группы ролей ещё не созданы: " + ", ".join(missing_groups) + ". Выполните seed_roles."
        )
    contract_names = set(configs)
    current_role_groups = list(locked_target.groups.filter(name__in=contract_names))
    if current_role_groups:
        locked_target.groups.remove(*current_role_groups)
    if selected_groups:
        locked_target.groups.add(*selected_groups)
    flags_changed = _technical_flag_changes(flags_before, flags_after)
    if flags_changed:
        locked_target.is_staff = flags_after["is_staff"]
        locked_target.is_superuser = flags_after["is_superuser"]
        locked_target.save(update_fields=[item["code"] for item in flags_changed])

    preview_fingerprint = hashlib.sha256(preview_token.encode("utf-8")).hexdigest()
    if AccessAssignmentAudit.objects.filter(preview_fingerprint=preview_fingerprint).exists():
        raise ValidationError("Этот предпросмотр уже был применён. Выполните новый предпросмотр.")
    try:
        with transaction.atomic():
            audit = AccessAssignmentAudit.objects.create(
                actor=locked_actor,
                target_user=locked_target,
                roles_before=before,
                roles_after=after,
                roles_added=added,
                roles_removed=removed,
                flags_before=flags_before,
                flags_after=flags_after,
                flags_changed=flags_changed,
                risk_markers=risk_markers,
                risk_confirmed=bool(risk_markers and risk_confirmed),
                source=source,
                is_break_glass=is_break_glass,
                reason=reason,
                preview_fingerprint=preview_fingerprint,
            )
    except IntegrityError as exc:
        raise ValidationError(
            "Этот предпросмотр уже был применён. Выполните новый предпросмотр."
        ) from exc
    return locked_target, audit


def _technical_flags_for_user(user):
    return {
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
    }


def _current_access_actor(actor):
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        raise PermissionDenied("Требуется вход в систему.")
    return get_user_model().objects.get(pk=actor.pk)


def _actor_access_state(actor):
    return {
        "is_active": bool(actor.is_active),
        "is_staff": bool(actor.is_staff),
        "is_superuser": bool(actor.is_superuser),
        "roles": selected_role_names_for_user(actor),
    }


def _validate_assignment_context(*, actor, source, reason):
    valid_sources = {value for value, _label in AccessAssignmentAudit.Source.choices}
    if source not in valid_sources:
        raise ValidationError("Неизвестный источник изменения доступа.")
    normalized_reason = str(reason or "").strip()
    if len(normalized_reason) > 1000:
        raise ValidationError("Причина изменения доступа не должна превышать 1000 символов.")
    is_break_glass = source == AccessAssignmentAudit.Source.DJANGO_ADMIN_BREAK_GLASS
    if source in {AccessAssignmentAudit.Source.AI, AccessAssignmentAudit.Source.AD_SYNC}:
        raise PermissionDenied(
            "Этот источник доступен только специализированному системному сервису."
        )
    if is_break_glass:
        if not actor.is_active or not actor.is_superuser:
            raise PermissionDenied("Резервное изменение доступно только активному суперпользователю.")
        if not normalized_reason:
            raise ValidationError("Для резервного изменения укажите причину.")
    return source, normalized_reason, is_break_glass


def _validate_role_assignment_authority(*, actor, target_user, before, after):
    changed_roles = set(before) ^ set(after)
    if not changed_roles:
        return
    if actor.is_active and actor.is_superuser:
        return
    if target_user.pk == actor.pk:
        raise PermissionDenied("Назначать роли самому себе может только суперпользователь.")

    allowlist = role_assignment_allowlist()
    actor_roles = selected_role_names_for_user(actor)
    allowed_roles = {
        target_role
        for actor_role in actor_roles
        for target_role in allowlist.get(actor_role, ())
    }
    forbidden_roles = sorted(changed_roles - allowed_roles)
    if forbidden_roles:
        raise PermissionDenied(
            "Недостаточно прав для изменения ролей: " + ", ".join(forbidden_roles) + "."
        )
    configs = contract_role_configs()
    critical_roles = sorted(
        role for role in changed_roles if _role_has_critical_capability(configs.get(role, {}))
    )
    if critical_roles:
        raise PermissionDenied(
            "Критичные роли может изменять только суперпользователь: "
            + ", ".join(critical_roles)
            + "."
        )


def _role_has_critical_capability(config):
    catalog = capability_catalog()
    return any(
        isinstance(catalog.get(capability), dict)
        and catalog[capability].get("risk") == "critical"
        and value not in (None, False, "", "none", [], {})
        for capability, value in config.items()
    )


def _assignment_context_risk_markers(
    *, actor, target_user, before, after, is_break_glass
):
    markers = []
    if actor.pk == target_user.pk and set(before) != set(after):
        markers.append(SELF_ASSIGNMENT_RISK_MARKER)
    if is_break_glass:
        markers.append(BREAK_GLASS_RISK_MARKER)
    return markers


def _requested_technical_flags(user, *, is_staff=None, is_superuser=None):
    for name, value in (("is_staff", is_staff), ("is_superuser", is_superuser)):
        if value is not None and not isinstance(value, bool):
            raise ValidationError(f"Флаг {name} должен быть логическим значением.")
    current = _technical_flags_for_user(user)
    return {
        "is_staff": current["is_staff"] if is_staff is None else is_staff,
        "is_superuser": current["is_superuser"] if is_superuser is None else is_superuser,
    }


def _technical_flag_changes(before, after):
    return [
        {
            "code": code,
            "label": PRIVILEGED_FLAG_LABELS[code],
            "before": before[code],
            "after": after[code],
        }
        for code in PRIVILEGED_FLAG_LABELS
        if before[code] != after[code]
    ]


def _technical_flag_risk_markers(before, after):
    return [
        f"{PRIVILEGED_FLAG_LABELS[code]}: выдаётся чувствительный доступ"
        for code in PRIVILEGED_FLAG_LABELS
        if not before[code] and after[code]
    ]


def _validate_technical_flag_change(*, actor, target_user, before, after):
    changed = _technical_flag_changes(before, after)
    if after["is_superuser"] and not after["is_staff"]:
        raise ValidationError("Супер-пользователь должен иметь доступ к администрированию.")
    if not changed:
        return
    actor_is_current_superuser = bool(
        getattr(actor, "is_authenticated", False)
        and get_user_model().objects.filter(
            pk=getattr(actor, "pk", None),
            is_active=True,
            is_superuser=True,
        ).exists()
    )
    if not actor_is_current_superuser:
        raise PermissionDenied("Технические флаги может изменять только суперпользователь.")
    if target_user.pk == getattr(actor, "pk", None) and before["is_superuser"] and not after["is_superuser"]:
        raise ValidationError("Нельзя снять права супер-пользователя у собственной учетной записи.")
    if before["is_superuser"] and not after["is_superuser"]:
        active_superuser_ids = list(
            get_user_model()
            .objects.select_for_update()
            .filter(is_active=True, is_superuser=True)
            .values_list("pk", flat=True)
        )
        if not any(pk != target_user.pk for pk in active_superuser_ids):
            raise ValidationError("Нельзя снять права у последнего активного супер-пользователя.")


def create_local_user(*, actor, cleaned_data, audit_callback=None):
    """Создать пользователя под общей блокировкой контура доступа."""
    payload = dict(cleaned_data)
    password = payload.pop("password", "")
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            return _create_local_user_locked(
                actor=actor,
                cleaned_data=payload,
                password=password,
                audit_callback=audit_callback,
            )
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


@transaction.atomic
def _create_local_user_locked(*, actor, cleaned_data, password, audit_callback=None):
    User = get_user_model()
    locked_actor = User.objects.select_for_update().get(pk=actor.pk)
    _require_superuser(locked_actor)
    User = get_user_model()
    forbidden_fields = {"groups", "user_permissions", "is_staff", "is_superuser"}
    submitted_forbidden = sorted(forbidden_fields & set(cleaned_data))
    if submitted_forbidden:
        raise ValidationError(
            "Поля доступа изменяются только через управляемое назначение: "
            + ", ".join(submitted_forbidden)
            + "."
        )
    _validate_managed_department(cleaned_data, required=True)
    user = User(**cleaned_data)
    if password:
        user.set_password(password)
    else:
        user.set_unusable_password()
    user.save()
    if audit_callback is not None:
        audit_callback({}, _user_profile_state(user))
    return user


def get_or_create_external_user(*, username, defaults=None, audit_callback=None):
    """Создать активного внешнего пользователя без гонки с ACL/role preview."""
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            return _get_or_create_external_user_locked(
                username=username,
                defaults=dict(defaults or {}),
                audit_callback=audit_callback,
            )
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


@transaction.atomic
def _get_or_create_external_user_locked(*, username, defaults, audit_callback=None):
    User = get_user_model()
    existing = User.objects.select_for_update().filter(username=username).first()
    if existing is not None:
        return existing, False
    forbidden_fields = {"groups", "user_permissions", "is_staff", "is_superuser"}
    if forbidden_fields & set(defaults):
        raise ValidationError("Внешнее создание не может назначать права напрямую.")
    user = User(username=username, **{"is_active": True, **defaults})
    user.set_unusable_password()
    user.save()
    if audit_callback is not None:
        audit_callback({}, _user_profile_state(user))
    return user, True


def update_local_user(
    *,
    actor,
    user,
    cleaned_data,
    locked_precondition=None,
    audit_callback=None,
):
    """Изменить профиль и lifecycle пользователя одним сериализованным commit."""
    payload = dict(cleaned_data)
    password = payload.pop("password", "")
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            return _update_local_user_locked(
                actor=actor,
                user=user,
                cleaned_data=payload,
                password=password,
                locked_precondition=locked_precondition,
                audit_callback=audit_callback,
            )
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


@transaction.atomic
def _update_local_user_locked(
    *,
    actor,
    user,
    cleaned_data,
    password,
    locked_precondition=None,
    audit_callback=None,
):
    User = get_user_model()
    locked_actor = User.objects.select_for_update().get(pk=actor.pk)
    _require_superuser(locked_actor)
    forbidden_fields = {"groups", "user_permissions", "is_staff", "is_superuser"}
    submitted_forbidden = sorted(forbidden_fields & set(cleaned_data))
    if submitted_forbidden:
        raise ValidationError(
            "Поля доступа изменяются только через управляемое назначение: "
            + ", ".join(submitted_forbidden)
            + "."
        )
    _validate_managed_department(cleaned_data)
    locked_user = (
        locked_actor
        if user.pk == locked_actor.pk
        else User.objects.select_for_update().get(pk=user.pk)
    )
    before_profile = _user_profile_state(locked_user)
    before_access = user_access_state(locked_user)
    if locked_precondition is not None:
        locked_precondition(locked_actor, locked_user, before_access)
    requested_is_active = cleaned_data.pop("is_active", locked_user.is_active)
    _validate_user_active_change(
        actor=locked_actor,
        user=locked_user,
        requested_is_active=requested_is_active,
    )
    for field, value in cleaned_data.items():
        setattr(locked_user, field, value)
    locked_user.is_active = requested_is_active
    if password:
        locked_user.set_password(password)
    locked_user.save()
    if audit_callback is not None:
        audit_callback(before_profile, _user_profile_state(locked_user))
    return locked_user


def disable_local_user(*, actor, user, audit_callback=None):
    return update_local_user(
        actor=actor,
        user=user,
        cleaned_data={"is_active": False},
        audit_callback=audit_callback,
    )


def initialize_demo_user_access(
    *, user, role_name, is_staff, reason, profile_updates=None
):
    """Аудируемо инициализировать доступ учётной записи демо-набора."""
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            return _initialize_demo_user_access_locked(
                user=user,
                role_name=role_name,
                is_staff=is_staff,
                reason=reason,
                profile_updates=dict(profile_updates or {}),
            )
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


@transaction.atomic
def _initialize_demo_user_access_locked(
    *, user, role_name, is_staff, reason, profile_updates
):
    roles_after = _validate_role_names([role_name])
    if not str(reason or "").strip():
        raise ValidationError("Для bootstrap-назначения требуется причина.")
    locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
    password = profile_updates.pop("password", "")
    _validate_managed_department(profile_updates)
    for field, value in profile_updates.items():
        setattr(locked_user, field, value)
    if password:
        locked_user.set_password(password)
    roles_before = selected_role_names_for_user(locked_user)
    flags_before = _technical_flags_for_user(locked_user)
    flags_after = {"is_staff": bool(is_staff), "is_superuser": False}
    profile_changed = bool(profile_updates or password)
    if roles_before == roles_after and flags_before == flags_after:
        if profile_changed:
            locked_user.save()
        return locked_user, None
    role_group = Group.objects.filter(name=role_name).first()
    if role_group is None:
        raise ValidationError(f"Группа роли '{role_name}' не создана.")
    current_role_groups = list(
        locked_user.groups.filter(name__in=contract_role_configs())
    )
    if current_role_groups:
        locked_user.groups.remove(*current_role_groups)
    locked_user.groups.add(role_group)
    locked_user.is_staff = flags_after["is_staff"]
    locked_user.is_superuser = False
    locked_user.save()
    audit = AccessAssignmentAudit.objects.create(
        actor=None,
        target_user=locked_user,
        roles_before=roles_before,
        roles_after=roles_after,
        roles_added=sorted(set(roles_after) - set(roles_before)),
        roles_removed=sorted(set(roles_before) - set(roles_after)),
        flags_before=flags_before,
        flags_after=flags_after,
        flags_changed=_technical_flag_changes(flags_before, flags_after),
        risk_markers=[],
        risk_confirmed=False,
        source=AccessAssignmentAudit.Source.SYSTEM_BOOTSTRAP,
        is_break_glass=False,
        reason=str(reason).strip(),
    )
    return locked_user, audit


def _validate_user_active_change(*, actor, user, requested_is_active):
    if not isinstance(requested_is_active, bool):
        raise ValidationError("Флаг активности должен быть логическим значением.")
    if requested_is_active or not user.is_active:
        return
    if user.pk == getattr(actor, "pk", None):
        raise ValidationError("Нельзя отключить собственную учетную запись.")
    if not user.is_superuser:
        return
    active_superusers = list(
        get_user_model()
        .objects.select_for_update()
        .filter(is_active=True, is_superuser=True)
        .values_list("pk", flat=True)
    )
    if len(active_superusers) == 1 and active_superusers[0] == user.pk:
        raise ValidationError("Нельзя отключить последнего активного супер-пользователя.")


def _validate_managed_department(cleaned_data, *, required=False):
    has_department = "department" in cleaned_data or "department_id" in cleaned_data
    if not has_department:
        if required:
            raise ValidationError("Для локального пользователя нужно выбрать подразделение.")
        return
    department = cleaned_data.get("department", cleaned_data.get("department_id"))
    department_id = getattr(department, "pk", department)
    if not department_id or not available_user_departments().filter(pk=department_id).exists():
        raise ValidationError("Выберите рабочее подразделение из доступного справочника.")


def link_ad_identity(*, actor, user, cleaned_data, audit_callback=None):
    """Привязать внешний субъект под общей блокировкой и с атомарным аудитом."""
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            return _link_ad_identity_locked(
                actor=actor,
                user=user,
                cleaned_data=dict(cleaned_data),
                audit_callback=audit_callback,
            )
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


@transaction.atomic
def _link_ad_identity_locked(*, actor, user, cleaned_data, audit_callback=None):
    User = get_user_model()
    locked_actor = User.objects.select_for_update().get(pk=actor.pk)
    _require_superuser(locked_actor)
    locked_user = (
        locked_actor
        if user.pk == locked_actor.pk
        else User.objects.select_for_update().get(pk=user.pk)
    )
    provider = cleaned_data.get("provider") or ExternalIdentity.Provider.ACTIVE_DIRECTORY
    subject_id = cleaned_data.get("subject_id", "")
    username = cleaned_data.get("username", "")
    domain = cleaned_data.get("domain", "")
    if not (subject_id or username or cleaned_data.get("upn")):
        raise ValidationError("Для связи с AD нужен SID, логин или UPN.")
    identity = (
        ExternalIdentity.objects.select_for_update()
        .filter(user=locked_user, provider=provider)
        .first()
    )
    before = _external_identity_state(identity)
    if identity is None:
        identity = ExternalIdentity(user=locked_user, provider=provider)
    identity.subject_id = subject_id
    identity.username = username
    identity.upn = cleaned_data.get("upn", "")
    identity.distinguished_name = cleaned_data.get("distinguished_name", "")
    identity.domain = domain
    identity.sync_status = (
        cleaned_data.get("sync_status") or ExternalIdentity.SyncStatus.MANUAL
    )
    identity.last_synced_at = timezone.now()
    identity.last_error = ""
    identity.save()
    if audit_callback is not None:
        audit_callback(before, _external_identity_state(identity))
    return identity


def user_access_state(user):
    """Минимальное состояние, определяющее доступ пользователя, без PII."""
    return {
        "user_id": user.pk,
        "is_active": bool(user.is_active),
        "department_id": user.department_id,
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
        "roles": selected_role_names_for_user(user),
    }


def audit_identity_fingerprint(field_name, value):
    """Версионированный HMAC-отпечаток идентификатора для безопасного аудита."""
    version = str(
        getattr(settings, "LOCAL_BUSINESS_AUDIT_FINGERPRINT_KEY_VERSION", "v1")
        or "v1"
    )
    secret = str(
        getattr(settings, "LOCAL_BUSINESS_AUDIT_FINGERPRINT_KEY", settings.SECRET_KEY)
    )
    normalized = _normalize_audit_identity_value(field_name, value)
    if not normalized:
        return {"present": False, "fingerprint": "", "key_version": version}
    digest = salted_hmac(
        f"accounts.audit-identity.{version}.{field_name}",
        normalized,
        secret=secret,
        algorithm="sha256",
    ).hexdigest()
    return {"present": True, "fingerprint": digest, "key_version": version}


def user_profile_audit_snapshot(user):
    """Безопасный снимок профиля: только идентификаторы БД и HMAC-отпечатки PII."""
    if not user:
        return {}
    return {
        "user_id": _state_value(user, "user_id", "pk"),
        "department_id": _state_value(user, "department_id"),
        "is_active": bool(_state_value(user, "is_active")),
        "username_fingerprint": audit_identity_fingerprint(
            "username", _state_value(user, "username")
        ),
        "email_fingerprint": audit_identity_fingerprint(
            "email", _state_value(user, "email")
        ),
        "first_name_fingerprint": audit_identity_fingerprint(
            "first_name", _state_value(user, "first_name")
        ),
        "last_name_fingerprint": audit_identity_fingerprint(
            "last_name", _state_value(user, "last_name")
        ),
    }


def external_identity_audit_snapshot(identity):
    """Безопасный снимок AD-привязки без исходных principal-значений."""
    if identity is None or not _state_value(identity, "identity_exists", default=True):
        return {"identity_exists": False}
    return {
        "identity_exists": True,
        "identity_id": _state_value(identity, "identity_id", "pk"),
        "user_id": _state_value(identity, "user_id"),
        "provider": _state_value(identity, "provider"),
        "sync_status": _state_value(identity, "sync_status"),
        "subject_fingerprint": audit_identity_fingerprint(
            "subject_id", _state_value(identity, "subject_id")
        ),
        "username_fingerprint": audit_identity_fingerprint(
            "username", _state_value(identity, "username")
        ),
        "upn_fingerprint": audit_identity_fingerprint(
            "upn", _state_value(identity, "upn")
        ),
        "distinguished_name_fingerprint": audit_identity_fingerprint(
            "distinguished_name", _state_value(identity, "distinguished_name")
        ),
        "domain_fingerprint": audit_identity_fingerprint(
            "domain", _state_value(identity, "domain")
        ),
    }


def _normalize_audit_identity_value(field_name, value):
    normalized = str(value or "").strip()
    if field_name in {"username", "email", "upn", "domain"}:
        return normalized.casefold()
    return normalized


def _state_value(value, key, fallback_key=None, default=None):
    if isinstance(value, dict):
        return value.get(key, value.get(fallback_key, default) if fallback_key else default)
    if hasattr(value, key):
        return getattr(value, key)
    if fallback_key and hasattr(value, fallback_key):
        return getattr(value, fallback_key)
    return default


def _user_profile_state(user):
    return {
        "user_id": user.pk,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "department_id": user.department_id,
        "is_active": bool(user.is_active),
    }


def _external_identity_state(identity):
    if identity is None:
        return {"identity_exists": False}
    return {
        "identity_exists": True,
        "identity_id": identity.pk,
        "user_id": identity.user_id,
        "provider": identity.provider,
        "subject_id": identity.subject_id,
        "username": identity.username,
        "upn": identity.upn,
        "distinguished_name": identity.distinguished_name,
        "domain": identity.domain,
        "sync_status": identity.sync_status,
    }


def sync_external_user_from_attributes(
    *,
    user,
    profile_updates,
    attributes,
    domain="",
    sync_identity=False,
    audit_callback,
):
    """Синхронизировать профиль/AD principal под lock, с аудитом и active guard."""
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            return _sync_external_user_from_attributes_locked(
                user=user,
                profile_updates=dict(profile_updates or {}),
                attributes=dict(attributes or {}),
                domain=domain,
                sync_identity=sync_identity,
                audit_callback=audit_callback,
            )
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


@transaction.atomic
def _sync_external_user_from_attributes_locked(
    *, user, profile_updates, attributes, domain, sync_identity, audit_callback
):
    locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
    if not locked_user.is_active:
        return locked_user
    allowed_profile_fields = {"email", "first_name", "last_name"}
    unknown_profile_fields = sorted(set(profile_updates) - allowed_profile_fields)
    if unknown_profile_fields:
        raise ValidationError(
            "AD-синхронизация передала недопустимые поля профиля: "
            + ", ".join(unknown_profile_fields)
            + "."
        )
    profile_before = _user_profile_state(locked_user)
    for field, value in profile_updates.items():
        setattr(locked_user, field, value)
    if profile_updates:
        locked_user.save(update_fields=sorted(profile_updates))

    identity_before = {"identity_exists": False}
    identity_after = identity_before
    identity = None
    if sync_identity:
        safe_attributes = {
            key: value
            for key, value in attributes.items()
            if key in SAFE_AD_ATTRIBUTE_KEYS
        }
        identity = (
            ExternalIdentity.objects.select_for_update()
            .filter(
                user=locked_user,
                provider=ExternalIdentity.Provider.ACTIVE_DIRECTORY,
            )
            .first()
        )
        identity_before = _external_identity_state(identity)
        if identity is None:
            identity = ExternalIdentity(
                user=locked_user,
                provider=ExternalIdentity.Provider.ACTIVE_DIRECTORY,
            )
        identity.subject_id = str(safe_attributes.get("objectSid", ""))
        identity.username = str(safe_attributes.get("sAMAccountName", ""))
        identity.upn = str(safe_attributes.get("userPrincipalName", ""))
        identity.domain = domain
        identity.attributes = safe_attributes
        identity.sync_status = ExternalIdentity.SyncStatus.VERIFIED
        identity.last_synced_at = timezone.now()
        identity.last_error = ""
        identity.save()
        identity_after = _external_identity_state(identity)

    profile_after = _user_profile_state(locked_user)
    if profile_before != profile_after or identity_before != identity_after:
        audit_callback(profile_before, profile_after, identity_before, identity_after)
    return locked_user


def upsert_ad_identity_from_attributes(*, user, attributes, domain="", audit_callback):
    """Явный audited automatic-link API; manual mode не вызывает этот путь."""
    synced_user = sync_external_user_from_attributes(
        user=user,
        profile_updates={},
        attributes=attributes,
        domain=domain,
        sync_identity=True,
        audit_callback=audit_callback,
    )
    return ExternalIdentity.objects.get(
        user=synced_user,
        provider=ExternalIdentity.Provider.ACTIVE_DIRECTORY,
    )


def refresh_external_user_authentication_state(user):
    """Прочитать activity под тем же lock, который использует отключение."""
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            return get_user_model().objects.get(pk=user.pk)
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


def scope_tokens_for_principal(*, sid="", username="", domain=""):
    tokens = set()
    if sid:
        identity = ExternalIdentity.objects.filter(
            provider=ExternalIdentity.Provider.ACTIVE_DIRECTORY,
            subject_id=sid,
        ).select_related("user").first()
        if identity and identity.user.is_active:
            tokens.add(f"user:{identity.user_id}")
    if username:
        qs = ExternalIdentity.objects.filter(
            provider=ExternalIdentity.Provider.ACTIVE_DIRECTORY,
            username__iexact=username,
        )
        if domain:
            qs = qs.filter(domain__iexact=domain)
        identity = qs.select_related("user").first()
        if identity and identity.user.is_active:
            tokens.add(f"user:{identity.user_id}")
    return tokens


def scope_tokens_for_group_names(group_names):
    tokens = set()
    existing = set(Group.objects.filter(name__in=list(group_names)).values_list("name", flat=True))
    tokens.update(f"role:{name}" for name in existing)
    return tokens


def _validate_role_names(role_names):
    requested = []
    for value in role_names or []:
        name = getattr(value, "name", value)
        if not isinstance(name, str) or not name or name.startswith("$"):
            raise ValidationError("Передан недопустимый идентификатор роли.")
        requested.append(name)
    canonical = sorted(set(requested))
    unknown = sorted(set(canonical) - set(contract_role_configs()))
    if unknown:
        raise ValidationError("Неизвестные роли: " + ", ".join(unknown))
    return canonical


def _load_preview_token(preview_token):
    if not preview_token:
        raise ValidationError("Сначала выполните предпросмотр изменения доступа.")
    try:
        payload = signing.loads(
            preview_token,
            salt=ACCESS_PREVIEW_SIGNING_SALT,
            max_age=ACCESS_PREVIEW_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise ValidationError("Предпросмотр устарел. Выполните его снова.") from exc
    except signing.BadSignature as exc:
        raise ValidationError("Подпись предпросмотра недействительна.") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Предпросмотр имеет неверный формат.")
    return payload


def _require_role_manager(actor):
    if (
        not getattr(actor, "is_authenticated", False)
        or not getattr(actor, "is_active", False)
        or not can_manage_roles(actor)
    ):
        raise PermissionDenied("Требуется право управления ролями.")


def _require_superuser(actor):
    if not getattr(actor, "pk", None) or not get_user_model().objects.filter(
        pk=actor.pk,
        is_active=True,
        is_superuser=True,
    ).exists():
        raise PermissionDenied("Требуются права суперпользователя.")
