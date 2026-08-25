"""Экспертный preview/apply-контур технических групп памяти."""
from __future__ import annotations

import hashlib
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.core.file_locks import (
    FileLockTimeoutError,
    access_control_write_lock_path,
    exclusive_file_lock,
)

from .models import MemoryGroupMembershipAudit
from .policies import MEMORY_REVIEW_GROUP_CAPABILITIES


MEMORY_GROUP_PREVIEW_SALT = "memory.group-membership-preview.v1"
MEMORY_GROUP_PREVIEW_MAX_AGE_SECONDS = 600


def memory_group_choices():
    from .policies import MEMORY_REVIEW_GROUP_PROFILES

    return [
        {
            "code": code,
            "label": MEMORY_REVIEW_GROUP_PROFILES.get(code, (code, ""))[0],
            "description": MEMORY_REVIEW_GROUP_PROFILES.get(code, (code, ""))[1],
        }
        for code in sorted(MEMORY_REVIEW_GROUP_CAPABILITIES)
    ]


def preview_memory_group_membership(*, actor, target_user, selected_group_names, reason):
    actor = _current_memory_group_editor(actor)
    target = get_user_model().objects.get(pk=target_user.pk)
    after = _validate_memory_groups(selected_group_names)
    reason = _validate_reason(reason)
    before = _current_memory_groups(target)
    if before == after:
        raise ValidationError("Технические группы памяти не изменились.")
    payload = {
        "actor_id": actor.pk,
        "actor_state": _actor_state(actor),
        "target_id": target.pk,
        "target_state": _target_state(target),
        "before": before,
        "after": after,
        "reason": reason,
        "nonce": str(uuid.uuid4()),
    }
    return {
        "before": before,
        "after": after,
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "reason": reason,
        "requires_confirmation": True,
        "preview_token": signing.dumps(payload, salt=MEMORY_GROUP_PREVIEW_SALT, compress=True),
    }


def apply_memory_group_membership(
    *, actor, target_user, selected_group_names, reason, preview_token, confirmed
):
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            return _apply_memory_group_membership_locked(
                actor=actor,
                target_user=target_user,
                selected_group_names=selected_group_names,
                reason=reason,
                preview_token=preview_token,
                confirmed=confirmed,
            )
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


def save_memory_group_membership(
    *, actor, target_user, selected_group_names, reason
):
    """Атомарно сохранить технические группы одной web-командой."""

    preview = preview_memory_group_membership(
        actor=actor,
        target_user=target_user,
        selected_group_names=selected_group_names,
        reason=reason,
    )
    return apply_memory_group_membership(
        actor=actor,
        target_user=target_user,
        selected_group_names=selected_group_names,
        reason=reason,
        preview_token=preview["preview_token"],
        confirmed=True,
    )


@transaction.atomic
def _apply_memory_group_membership_locked(
    *, actor, target_user, selected_group_names, reason, preview_token, confirmed
):
    if not confirmed:
        raise ValidationError("Подтвердите изменение технических полномочий памяти.")
    signed = _load_preview(preview_token)
    after = _validate_memory_groups(selected_group_names)
    reason = _validate_reason(reason)
    user_model = get_user_model()
    locked_actor = user_model.objects.select_for_update().get(pk=actor.pk)
    _require_memory_group_editor(locked_actor)
    locked_target = user_model.objects.select_for_update().get(pk=target_user.pk)
    if signed.get("actor_id") != locked_actor.pk or signed.get("target_id") != locked_target.pk:
        raise ValidationError("Предпросмотр относится к другому пользователю или администратору.")
    if signed.get("actor_state") != _actor_state(locked_actor):
        raise ValidationError("Права администратора изменились после предпросмотра.")
    if signed.get("target_state") != _target_state(locked_target):
        raise ValidationError("Доступ пользователя изменился после предпросмотра.")
    if signed.get("before") != _current_memory_groups(locked_target):
        raise ValidationError("Технические группы уже изменились. Повторите предпросмотр.")
    if signed.get("after") != after or signed.get("reason") != reason:
        raise ValidationError("Поля формы изменились после предпросмотра.")

    groups = list(Group.objects.filter(name__in=after))
    known_names = {group.name for group in groups}
    missing = sorted(set(after) - known_names)
    if missing:
        raise ValidationError("Технические группы не созданы: " + ", ".join(missing) + ".")
    before = signed["before"]
    memory_names = set(MEMORY_REVIEW_GROUP_CAPABILITIES)
    locked_target.groups.remove(*locked_target.groups.filter(name__in=memory_names))
    locked_target.groups.add(*groups)
    fingerprint = hashlib.sha256(preview_token.encode("utf-8")).hexdigest()
    try:
        audit = MemoryGroupMembershipAudit.objects.create(
            actor=locked_actor,
            target_user=locked_target,
            groups_before=before,
            groups_after=after,
            groups_added=sorted(set(after) - set(before)),
            groups_removed=sorted(set(before) - set(after)),
            reason=reason,
            preview_fingerprint=fingerprint,
        )
    except IntegrityError as exc:
        raise ValidationError("Этот предпросмотр уже был применён.") from exc
    return locked_target, audit


def _current_memory_group_editor(actor):
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        raise PermissionDenied("Требуется вход в систему.")
    current = get_user_model().objects.get(pk=actor.pk)
    _require_memory_group_editor(current)
    return current


def _require_memory_group_editor(actor):
    if not actor.is_active or not actor.is_superuser:
        raise PermissionDenied("Технические группы памяти изменяет только активный суперпользователь.")


def _validate_memory_groups(group_names):
    if not isinstance(group_names, (list, tuple, set)):
        raise ValidationError("Технические группы должны быть списком.")
    normalized = sorted({str(name).strip() for name in group_names if str(name).strip()})
    unknown = sorted(set(normalized) - set(MEMORY_REVIEW_GROUP_CAPABILITIES))
    if unknown:
        raise ValidationError("Неизвестные технические группы памяти: " + ", ".join(unknown) + ".")
    return normalized


def _validate_reason(reason):
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("Укажите причину изменения технических полномочий памяти.")
    if len(reason) > 1000:
        raise ValidationError("Причина не должна превышать 1000 символов.")
    return reason


def _actor_state(actor):
    return {
        "is_active": bool(actor.is_active),
        "is_superuser": bool(actor.is_superuser),
        "groups": sorted(actor.groups.values_list("name", flat=True)),
    }


def _target_state(target):
    return {
        "is_active": bool(target.is_active),
        "is_staff": bool(target.is_staff),
        "is_superuser": bool(target.is_superuser),
        "groups": sorted(target.groups.values_list("name", flat=True)),
    }


def _current_memory_groups(user):
    return sorted(
        user.groups.filter(name__in=MEMORY_REVIEW_GROUP_CAPABILITIES).values_list(
            "name", flat=True
        )
    )


def _load_preview(token):
    if not token:
        raise ValidationError("Сначала выполните предпросмотр изменения.")
    try:
        return signing.loads(
            token,
            salt=MEMORY_GROUP_PREVIEW_SALT,
            max_age=MEMORY_GROUP_PREVIEW_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise ValidationError("Срок предпросмотра истёк.") from exc
    except signing.BadSignature as exc:
        raise ValidationError("Предпросмотр изменения недействителен.") from exc
