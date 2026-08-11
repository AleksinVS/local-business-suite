from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.workorders.policies import can_manage_roles

from .models import AccessAssignmentAudit, ExternalIdentity
from .selectors import (
    access_assignment_consequences,
    contract_role_configs,
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


def preview_role_assignment(
    *,
    actor,
    target_user,
    selected_role_names,
    is_staff=None,
    is_superuser=None,
):
    """Строит канонический diff и подписывает его для последующего применения."""

    _require_role_manager(actor)
    after = _validate_role_names(selected_role_names)
    before = selected_role_names_for_user(target_user)
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
    flags_changed = _technical_flag_changes(flags_before, flags_after)
    payload = {
        "actor_id": actor.pk,
        "target_id": target_user.pk,
        "before": before,
        "after": after,
        "flags_before": flags_before,
        "flags_after": flags_after,
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
        "consequences": access_assignment_consequences(before, after),
        "preview_token": signing.dumps(payload, salt=ACCESS_PREVIEW_SIGNING_SALT, compress=True),
    }


@transaction.atomic
def apply_role_assignment(
    *,
    actor,
    target_user,
    selected_role_names,
    preview_token,
    risk_confirmed=False,
    is_staff=None,
    is_superuser=None,
):
    """Меняет контрактные роли и технические флаги в одной транзакции."""

    _require_role_manager(actor)
    after = _validate_role_names(selected_role_names)
    signed_preview = _load_preview_token(preview_token)
    flags_after = _requested_technical_flags(
        target_user,
        is_staff=is_staff,
        is_superuser=is_superuser,
    )
    if signed_preview.get("actor_id") != actor.pk or signed_preview.get("target_id") != target_user.pk:
        raise ValidationError("Предпросмотр относится к другому пользователю или администратору.")
    if signed_preview.get("after") != after:
        raise ValidationError("Выбранные роли изменились после предпросмотра. Выполните предпросмотр снова.")
    if signed_preview.get("flags_after") != flags_after:
        raise ValidationError("Технические флаги изменились после предпросмотра. Выполните предпросмотр снова.")

    User = get_user_model()
    locked_target = User.objects.select_for_update().get(pk=target_user.pk)
    before = selected_role_names_for_user(locked_target)
    flags_before = _technical_flags_for_user(locked_target)
    if signed_preview.get("before") != before:
        raise ValidationError("Роли пользователя уже изменены. Выполните предпросмотр снова.")
    if signed_preview.get("flags_before") != flags_before:
        raise ValidationError("Технические флаги пользователя уже изменены. Выполните предпросмотр снова.")
    _validate_technical_flag_change(
        actor=actor,
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

    audit = AccessAssignmentAudit.objects.create(
        actor=actor,
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
    )
    return locked_target, audit


def _technical_flags_for_user(user):
    return {
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
    }


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
        other_superuser_exists = get_user_model().objects.filter(
            is_active=True,
            is_superuser=True,
        ).exclude(pk=target_user.pk).exists()
        if not other_superuser_exists:
            raise ValidationError("Нельзя снять права у последнего активного супер-пользователя.")


def create_local_user(*, actor, cleaned_data):
    _require_superuser(actor)
    User = get_user_model()
    if "groups" in cleaned_data:
        raise ValidationError("Группы назначаются только через карточку доступа.")
    password = cleaned_data.pop("password", "")
    user = User(**cleaned_data)
    if password:
        user.set_password(password)
    else:
        user.set_unusable_password()
    with transaction.atomic():
        user.save()
    return user


def update_local_user(*, actor, user, cleaned_data):
    _require_superuser(actor)
    if "groups" in cleaned_data:
        raise ValidationError("Группы назначаются только через карточку доступа.")
    password = cleaned_data.pop("password", "")
    for field, value in cleaned_data.items():
        setattr(user, field, value)
    if password:
        user.set_password(password)
    with transaction.atomic():
        user.save()
    return user


def disable_local_user(*, actor, user):
    _require_superuser(actor)
    if user.pk == getattr(actor, "pk", None):
        raise ValidationError("Нельзя отключить собственную учетную запись.")
    user.is_active = False
    user.save(update_fields=["is_active"])
    return user


def link_ad_identity(*, actor, user, cleaned_data):
    _require_superuser(actor)
    provider = cleaned_data.get("provider") or ExternalIdentity.Provider.ACTIVE_DIRECTORY
    subject_id = cleaned_data.get("subject_id", "")
    username = cleaned_data.get("username", "")
    domain = cleaned_data.get("domain", "")
    if not (subject_id or username or cleaned_data.get("upn")):
        raise ValidationError("Для связи с AD нужен SID, логин или UPN.")
    identity, _created = ExternalIdentity.objects.update_or_create(
        user=user,
        provider=provider,
        defaults={
            "subject_id": subject_id,
            "username": username,
            "upn": cleaned_data.get("upn", ""),
            "distinguished_name": cleaned_data.get("distinguished_name", ""),
            "domain": domain,
            "sync_status": cleaned_data.get("sync_status") or ExternalIdentity.SyncStatus.MANUAL,
            "last_synced_at": timezone.now(),
            "last_error": "",
        },
    )
    return identity


def upsert_ad_identity_from_attributes(*, user, attributes, domain=""):
    safe_attributes = {
        key: value for key, value in dict(attributes or {}).items() if key in SAFE_AD_ATTRIBUTE_KEYS
    }
    return ExternalIdentity.objects.update_or_create(
        user=user,
        provider=ExternalIdentity.Provider.ACTIVE_DIRECTORY,
        defaults={
            "subject_id": str(safe_attributes.get("objectSid", "")),
            "username": str(safe_attributes.get("sAMAccountName", "")),
            "upn": str(safe_attributes.get("userPrincipalName", "")),
            "domain": domain,
            "attributes": safe_attributes,
            "sync_status": ExternalIdentity.SyncStatus.VERIFIED,
            "last_synced_at": timezone.now(),
            "last_error": "",
        },
    )[0]


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
    if not getattr(actor, "is_authenticated", False) or not can_manage_roles(actor):
        raise PermissionDenied("Требуется право управления ролями.")


def _require_superuser(actor):
    if not getattr(actor, "is_superuser", False):
        raise PermissionDenied("Требуются права суперпользователя.")
