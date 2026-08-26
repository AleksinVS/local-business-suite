"""Прикладная координация единого черновика карточки пользователя.

Модуль не определяет правила доступа: каждый компонент подписывается и повторно
проверяется сервисом доменного владельца. Координатор обеспечивает один lock и
одну транзакцию, чтобы пользователь не получил частично сохранённую карточку.
"""
from __future__ import annotations

import uuid

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.selectors import selected_role_names_for_user
from apps.accounts.services import (
    _apply_external_identity_change_locked,
    _apply_role_assignment_locked,
    _apply_user_profile_change_locked,
    preview_external_identity_change,
    preview_role_assignment,
    preview_user_profile_change,
)
from apps.core.file_locks import (
    FileLockTimeoutError,
    access_control_write_lock_path,
    exclusive_file_lock,
)
from apps.memory.access_services import (
    _apply_memory_group_membership_locked,
    preview_memory_group_membership,
)
from apps.memory.policies import MEMORY_REVIEW_GROUP_CAPABILITIES


BUNDLE_PREVIEW_SALT = "settings-center.user-access-bundle-preview.v1"
BUNDLE_PREVIEW_MAX_AGE_SECONDS = 600


def preview_user_access_bundle(*, actor, target_user, cleaned_data):
    """Подписать все реально изменённые компоненты одного пользовательского черновика."""

    target = get_user_model().objects.get(pk=target_user.pk)
    payloads = _changed_component_payloads(target, cleaned_data)
    if not payloads:
        raise ValidationError("В карточке пользователя нет изменений.")
    if actor.pk == target.pk and "roles" in payloads and len(payloads) > 1:
        raise ValidationError(
            "Собственные роли суперпользователя сохраняются отдельно от других полей карточки."
        )
    reason = cleaned_data["reason"]
    component_previews = {}
    if "memory" in payloads:
        component_previews["memory"] = preview_memory_group_membership(
            actor=actor,
            target_user=target,
            selected_group_names=payloads["memory"],
            reason=reason,
        )
    if "roles" in payloads:
        component_previews["roles"] = preview_role_assignment(
            actor=actor,
            target_user=target,
            selected_role_names=payloads["roles"]["role_names"],
            is_staff=payloads["roles"]["is_staff"],
            is_superuser=payloads["roles"]["is_superuser"],
            reason=reason,
        )
    if "profile" in payloads:
        component_previews["profile"] = preview_user_profile_change(
            actor=actor,
            target_user=target,
            cleaned_data=payloads["profile"],
            reason=reason,
        )
    if "ad" in payloads:
        component_previews["ad"] = preview_external_identity_change(
            actor=actor,
            target_user=target,
            cleaned_data=payloads["ad"],
            reason=reason,
        )
    tokens = {
        name: preview["preview_token"] for name, preview in component_previews.items()
    }
    bundle_token = signing.dumps(
        {
            "actor_id": actor.pk,
            "target_id": target.pk,
            "components": sorted(tokens),
            "tokens": tokens,
            "nonce": str(uuid.uuid4()),
        },
        salt=BUNDLE_PREVIEW_SALT,
        compress=True,
    )
    return {
        "components": component_previews,
        "changes": _summary_changes(component_previews),
        "risk_markers": component_previews.get("roles", {}).get("risk_markers", []),
        "requires_risk_confirmation": bool(
            component_previews.get("roles", {}).get("risk_markers")
        ),
        "requires_memory_confirmation": "memory" in component_previews,
        "preview_token": bundle_token,
    }


def apply_user_access_bundle(
    *,
    actor,
    target_user,
    cleaned_data,
    preview_token,
    risk_confirmed=False,
    memory_confirmed=False,
    profile_audit_callback=None,
    ad_audit_callback=None,
):
    """Атомарно применить подписанные компоненты карточки через доменные сервисы."""

    signed = _load_bundle_preview(preview_token)
    if signed.get("actor_id") != actor.pk or signed.get("target_id") != target_user.pk:
        raise ValidationError("Предпросмотр относится к другой карточке или администратору.")
    target = get_user_model().objects.get(pk=target_user.pk)
    payloads = _changed_component_payloads(target, cleaned_data)
    expected_components = sorted(payloads)
    if signed.get("components") != expected_components:
        raise ValidationError("Состав изменений изменился после предпросмотра. Повторите проверку.")
    tokens = signed.get("tokens")
    if not isinstance(tokens, dict) or sorted(tokens) != expected_components:
        raise ValidationError("Предпросмотр карточки имеет неверный формат.")
    reason = cleaned_data["reason"]
    results = {}
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            with transaction.atomic():
                # Порядок важен: memory token включает полный набор групп, а role
                # token — только контрактные роли. Профиль не должен менять actor
                # state до проверки назначения роли.
                if "memory" in payloads:
                    results["memory"] = _apply_memory_group_membership_locked(
                        actor=actor,
                        target_user=target,
                        selected_group_names=payloads["memory"],
                        reason=reason,
                        preview_token=tokens["memory"],
                        confirmed=memory_confirmed,
                    )
                if "roles" in payloads:
                    role_payload = payloads["roles"]
                    results["roles"] = _apply_role_assignment_locked(
                        actor=actor,
                        target_user=target,
                        selected_role_names=role_payload["role_names"],
                        preview_token=tokens["roles"],
                        risk_confirmed=risk_confirmed,
                        is_staff=role_payload["is_staff"],
                        is_superuser=role_payload["is_superuser"],
                        reason=reason,
                    )
                if "profile" in payloads:
                    results["profile"] = _apply_user_profile_change_locked(
                        actor=actor,
                        target_user=target,
                        cleaned_data=payloads["profile"],
                        preview_token=tokens["profile"],
                        reason=reason,
                        audit_callback=profile_audit_callback,
                    )
                if "ad" in payloads:
                    results["ad"] = _apply_external_identity_change_locked(
                        actor=actor,
                        target_user=target,
                        cleaned_data=payloads["ad"],
                        preview_token=tokens["ad"],
                        reason=reason,
                        audit_callback=ad_audit_callback,
                    )
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc
    return get_user_model().objects.get(pk=target.pk), results


def save_user_access_bundle(
    *,
    actor,
    target_user,
    cleaned_data,
    profile_audit_callback=None,
    ad_audit_callback=None,
):
    """Атомарно сохранить всю карточку одним пользовательским POST.

    Вложенные планы компонентов остаются внутренней деталью сервиса:
    они строятся и применяются в одном вызове, а браузер не хранит токены.
    """

    preview = preview_user_access_bundle(
        actor=actor,
        target_user=target_user,
        cleaned_data=cleaned_data,
    )
    return apply_user_access_bundle(
        actor=actor,
        target_user=target_user,
        cleaned_data=cleaned_data,
        preview_token=preview["preview_token"],
        risk_confirmed=True,
        memory_confirmed=True,
        profile_audit_callback=profile_audit_callback,
        ad_audit_callback=ad_audit_callback,
    )


def _changed_component_payloads(target, cleaned_data):
    profile = {
        "username": cleaned_data["username"],
        "first_name": cleaned_data["first_name"],
        "last_name": cleaned_data["last_name"],
        "email": cleaned_data["email"],
        "department": cleaned_data["department"],
        "is_active": cleaned_data["is_active"],
    }
    if cleaned_data.get("password"):
        profile["password"] = cleaned_data["password"]
    profile_changed = bool(cleaned_data.get("password")) or any(
        (
            getattr(target, name if name != "department" else "department_id")
            != (getattr(value, "pk", value) if name == "department" else value)
        )
        for name, value in profile.items()
        if name != "password"
    )
    identity = target.external_identities.order_by("pk").first()
    ad = {
        "provider": cleaned_data["ad_provider"],
        "subject_id": cleaned_data["ad_subject_id"],
        "username": cleaned_data["ad_username"],
        "upn": cleaned_data["ad_upn"],
        "distinguished_name": cleaned_data["ad_distinguished_name"],
        "domain": cleaned_data["ad_domain"],
        "sync_status": cleaned_data["ad_sync_status"],
    }
    has_any_principal = any(
        str(ad[name] or "").strip() for name in ("subject_id", "username", "upn")
    )
    # Пустые AD-поля в общей форме означают отсутствие изменения AD-связи.
    ad_changed = False
    if has_any_principal:
        if identity:
            ad_changed = any(
                str(getattr(identity, name, "") or "") != str(ad[name] or "")
                for name in (
                    "provider",
                    "subject_id",
                    "username",
                    "upn",
                    "distinguished_name",
                    "domain",
                    "sync_status",
                )
            )
        else:
            ad_changed = True
    role_names = sorted(group.name for group in cleaned_data["roles"])
    roles_changed = (
        role_names != selected_role_names_for_user(target)
        or bool(cleaned_data["is_staff"]) != bool(target.is_staff)
        or bool(cleaned_data["is_superuser"]) != bool(target.is_superuser)
    )
    memory_names = sorted(cleaned_data["memory_group_names"])
    current_memory = sorted(
        target.groups.filter(name__in=MEMORY_REVIEW_GROUP_CAPABILITIES).values_list(
            "name", flat=True
        )
    )
    payloads = {}
    if profile_changed:
        payloads["profile"] = profile
    if ad_changed:
        payloads["ad"] = ad
    if roles_changed:
        payloads["roles"] = {
            "role_names": role_names,
            "is_staff": bool(cleaned_data["is_staff"]),
            "is_superuser": bool(cleaned_data["is_superuser"]),
        }
    if memory_names != current_memory:
        payloads["memory"] = memory_names
    return payloads


def _summary_changes(component_previews):
    labels = {
        "memory": "Группы памяти",
        "roles": "Должностные функции и административный доступ",
        "profile": "Профиль пользователя",
        "ad": "Связь с Active Directory",
    }
    summary = []
    for name, preview in component_previews.items():
        detail = preview.get("changes") or []
        if not detail:
            detail = [
                *[f"Добавлено: {value}" for value in preview.get("added", [])],
                *[f"Удалено: {value}" for value in preview.get("removed", [])],
            ]
        summary.append({"code": name, "label": labels[name], "details": detail})
    return summary


def _load_bundle_preview(token):
    if not token:
        raise ValidationError("Сначала проверьте все изменения карточки.")
    try:
        payload = signing.loads(
            token,
            salt=BUNDLE_PREVIEW_SALT,
            max_age=BUNDLE_PREVIEW_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise ValidationError("Предпросмотр карточки устарел. Повторите проверку.") from exc
    except signing.BadSignature as exc:
        raise ValidationError("Подпись предпросмотра карточки недействительна.") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Предпросмотр карточки имеет неверный формат.")
    return payload
