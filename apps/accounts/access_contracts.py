"""Предметный read/preview/apply-контур определений ролей доступа."""
from __future__ import annotations

import copy
import hashlib
import json
import uuid

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count

from apps.core.contract_store import get_contract, normalized_hash

from .selectors import capability_catalog, contract_role_configs, role_risk_markers


ROLE_DEFINITION_PREVIEW_SALT = "accounts.role-definition-preview.v1"
ROLE_DEFINITION_PREVIEW_MAX_AGE_SECONDS = 600

SCOPE_LABELS = {
    "all": "Все",
    "department_branch": "Ветка подразделения",
    "assigned_or_unassigned_or_authored": "Свои, назначенные и неназначенные",
    "assigned_or_unassigned": "Назначенные и неназначенные",
    "assigned": "Только назначенные",
    "visible": "Все видимые",
    "authored": "Только созданные пользователем",
    "none": "Нет доступа",
}

CAPABILITY_GROUP_LABELS = {
    "kanban": "Канбан-доска",
    "inventory": "Медизделия",
    "waiting_list": "Лист ожидания",
    "analytics": "Аналитика",
    "departments": "Подразделения",
    "access": "Доступ",
    "ai": "ИИ-центр",
    "memory": "Память организации",
    "other": "Прочие права",
}
CAPABILITY_GROUP_DESCRIPTIONS = {
    "memory": "Права памяти организации. Технические группы памяти назначаются отдельно в карточке пользователя.",
}
CAPABILITY_RISK_LABELS = {
    "elevated": "Повышенный риск",
    "critical": "Критический риск",
}

CAPABILITY_GROUP_BY_CAPABILITY = {
    "view_scope": "kanban",
    "create_workorder": "kanban",
    "edit_scope": "kanban",
    "comment_scope": "kanban",
    "upload_attachment_scope": "kanban",
    "manage_assignments": "kanban",
    "transition_scope": "kanban",
    "transition_targets": "kanban",
    "confirm_closure_scope": "kanban",
    "rate_scope": "kanban",
    "manage_board_columns": "kanban",
    "manage_inventory": "inventory",
    "view_waiting_list": "waiting_list",
    "create_waiting_list": "waiting_list",
    "view_analytics": "analytics",
    "manage_departments": "departments",
    "manage_roles": "access",
    "manage_ai_skills": "ai",
    "memory_organization_write": "memory",
    "memory_organization_review": "memory",
}


def capability_group_code(code, _metadata=None):
    """Return the explicit user-facing group; unknown runtime rights stay visible in ``other``."""
    return CAPABILITY_GROUP_BY_CAPABILITY.get(code, "other")


def capability_groups(catalog=None):
    """Build stable user-facing groups from the explicit map, then unknown rights."""
    catalog = catalog if isinstance(catalog, dict) else capability_catalog()
    groups = {
        code: {
            "code": code,
            "label": label,
            "description": CAPABILITY_GROUP_DESCRIPTIONS.get(code, ""),
            "capabilities": [],
        }
        for code, label in CAPABILITY_GROUP_LABELS.items()
    }
    for code, group in CAPABILITY_GROUP_BY_CAPABILITY.items():
        if code in catalog:
            groups[group]["capabilities"].append((code, catalog[code]))
    for code, metadata in catalog.items():
        if code not in CAPABILITY_GROUP_BY_CAPABILITY:
            groups["other"]["capabilities"].append((code, metadata))
    return [group for group in groups.values() if group["capabilities"]]


def role_catalog_rows():
    counts = {
        row["groups__name"]: row["total"]
        for row in get_user_model().objects.filter(
            groups__name__in=contract_role_configs()
        )
        .values("groups__name")
        .annotate(total=Count("id"))
    }
    rows = []
    for code, config in contract_role_configs().items():
        risk_markers = role_risk_markers(code, config)
        risk_labels = [marker.split(": ", 1)[-1] for marker in risk_markers]
        rows.append({
            "code": code,
            "label": config.get("display_name", code),
            "description": config.get("description", ""),
            "member_count": counts.get(code, 0),
            "risk_markers": risk_markers,
            "risk_labels": risk_labels[:3],
            "additional_risk_count": max(0, len(risk_labels) - 3),
        })
    return rows


def role_definition_read_model(role_code):
    rules = get_contract("role_rules")
    config = rules.get(role_code)
    if not isinstance(config, dict) or role_code.startswith("$"):
        raise ValidationError("Роль не найдена.")
    catalog = capability_catalog()
    sections = []
    for group in capability_groups(catalog):
        sections.append({
            "code": group["code"],
            "label": group["label"],
            "description": group.get("description", ""),
            "capabilities": [
                {
                    "code": code,
                    "label": metadata.get("label", code),
                    "description": metadata.get("description", ""),
                    "type": metadata.get("type", ""),
                    "risk": metadata.get("risk", "normal"),
                    "risk_label": CAPABILITY_RISK_LABELS.get(metadata.get("risk", "normal"), ""),
                    "value": copy.deepcopy(config.get(code)),
                }
                for code, metadata in group["capabilities"]
            ],
        })
    return {
        "code": role_code,
        "label": config.get("display_name", role_code),
        "description": config.get("description", ""),
        "config": copy.deepcopy(config),
        "sections": sections,
        "member_count": get_user_model().objects.filter(groups__name=role_code).distinct().count(),
        "base_hash": normalized_hash(rules),
    }


def preview_role_definition_change(*, actor, role_code, proposed_config, base_hash):
    actor = _require_role_definition_editor(actor)
    rules = get_contract("role_rules")
    if normalized_hash(rules) != str(base_hash or "").removeprefix("sha256:"):
        raise ValidationError("Контракт ролей уже изменился. Перезагрузите страницу.")
    before = rules.get(role_code)
    if not isinstance(before, dict) or role_code.startswith("$"):
        raise ValidationError("Роль не найдена.")
    after = _normalize_proposed_role(role_code=role_code, before=before, proposed=proposed_config)
    if before == after:
        raise ValidationError("В роли нет изменений для проверки.")

    candidate = copy.deepcopy(rules)
    candidate[role_code] = after
    from apps.settings_center.contract_services import parse_and_validate_payload
    from apps.settings_center.registry import get_registry

    descriptor = get_registry().get("core.contract.role_rules")
    parse_and_validate_payload(descriptor, json.dumps(candidate, ensure_ascii=False))
    changes = _role_definition_changes(before=before, after=after)
    impact = _role_change_impact(role_code=role_code, before=before, after=after)
    risk_markers = [
        f"{change['label']}: {change['risk_label']}"
        for change in changes
        if change["risk"] in {"elevated", "critical"}
    ]
    token_payload = {
        "actor_id": actor.pk,
        "actor_state": _role_editor_actor_state(actor),
        "role_code": role_code,
        "base_hash": normalized_hash(rules),
        "after": after,
        "member_fingerprint": _role_member_fingerprint(role_code),
        "impact_hash": normalized_hash(impact),
        "nonce": str(uuid.uuid4()),
    }
    return {
        "role": {"code": role_code, "label": after.get("display_name", role_code)},
        "base_hash": normalized_hash(rules),
        "changes": changes,
        "impact": impact,
        "risk_markers": risk_markers,
        "requires_confirmation": bool(risk_markers),
        "preview_token": signing.dumps(
            token_payload,
            salt=ROLE_DEFINITION_PREVIEW_SALT,
            compress=True,
        ),
        "proposed_config": after,
    }


def apply_role_definition_change(
    *, actor, role_code, proposed_config, base_hash, preview_token, risk_confirmed=False
):
    actor = _require_role_definition_editor(actor)
    signed = _load_role_definition_preview(preview_token)
    if signed.get("actor_id") != actor.pk or signed.get("role_code") != role_code:
        raise ValidationError("Предпросмотр относится к другой роли или администратору.")
    if signed.get("actor_state") != _role_editor_actor_state(actor):
        raise ValidationError("Права администратора изменились после предпросмотра.")
    if signed.get("base_hash") != str(base_hash or "").removeprefix("sha256:"):
        raise ValidationError("Версия формы не совпадает с предпросмотром.")
    rules = get_contract("role_rules")
    if normalized_hash(rules) != signed.get("base_hash"):
        raise ValidationError("Контракт ролей изменился после предпросмотра.")
    before = rules.get(role_code)
    after = _normalize_proposed_role(role_code=role_code, before=before, proposed=proposed_config)
    if signed.get("after") != after:
        raise ValidationError("Поля роли изменились после предпросмотра.")
    changes = _role_definition_changes(before=before, after=after)
    impact = _role_change_impact(role_code=role_code, before=before, after=after)
    if signed.get("member_fingerprint") != _role_member_fingerprint(role_code) or signed.get(
        "impact_hash"
    ) != normalized_hash(impact):
        raise ValidationError(
            "Состав участников роли или влияние изменения изменились. Выполните предпросмотр снова."
        )
    requires_confirmation = any(
        change["risk"] in {"elevated", "critical"} for change in changes
    )
    if requires_confirmation and not risk_confirmed:
        raise ValidationError("Изменение чувствительных прав требует подтверждения.")
    candidate = copy.deepcopy(rules)
    candidate[role_code] = after

    from apps.settings_center.contract_services import apply_contract_payload

    preview_fingerprint = hashlib.sha256(preview_token.encode("utf-8")).hexdigest()

    def locked_precondition(current_actor):
        if signed.get("actor_state") != _role_editor_actor_state(current_actor):
            raise ValidationError("Права администратора изменились после предпросмотра.")
        current_impact = _role_change_impact(role_code=role_code, before=before, after=after)
        if signed.get("member_fingerprint") != _role_member_fingerprint(role_code) or signed.get(
            "impact_hash"
        ) != normalized_hash(current_impact):
            raise ValidationError(
                "Состав участников роли или влияние изменения изменились. "
                "Выполните предпросмотр снова."
            )

    return apply_contract_payload(
        actor=actor,
        setting_id="core.contract.role_rules",
        raw_payload=json.dumps(candidate, ensure_ascii=False),
        confirmed=True,
        base_hash=signed["base_hash"],
        operation_fingerprint=preview_fingerprint,
        locked_precondition=locked_precondition,
        audit_context={
            "source": "role_definition_editor",
            "role_code": role_code,
            "impact": impact,
            "risk_markers": [
                change["code"]
                for change in changes
                if change["risk"] in {"elevated", "critical"}
            ],
        },
    )


def _require_role_definition_editor(actor):
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        raise PermissionDenied("Требуется вход в систему.")
    current = get_user_model().objects.get(pk=actor.pk)
    if not current.is_active or not current.is_superuser:
        raise PermissionDenied("Определения ролей может изменять только активный суперпользователь.")
    return current


def _role_editor_actor_state(actor):
    return {
        "is_active": bool(actor.is_active),
        "is_superuser": bool(actor.is_superuser),
        "roles": sorted(actor.groups.values_list("name", flat=True)),
    }


def _role_member_fingerprint(role_code):
    member_ids = list(
        get_user_model().objects.filter(groups__name=role_code)
        .order_by("pk")
        .values_list("pk", flat=True)
        .distinct()
    )
    return normalized_hash(member_ids)


def _normalize_proposed_role(*, role_code, before, proposed):
    if not isinstance(before, dict) or not isinstance(proposed, dict):
        raise ValidationError("Некорректное определение роли.")
    catalog = capability_catalog()
    metadata_fields = {"display_name", "description"}
    unknown = sorted(set(proposed) - set(catalog) - metadata_fields)
    if unknown:
        raise ValidationError(
            "Переданы неизвестные права роли: " + ", ".join(unknown) + "."
        )
    after = copy.deepcopy(before)
    for field in metadata_fields:
        if field in proposed:
            value = str(proposed[field] or "").strip()
            if field == "display_name" and not value:
                raise ValidationError("Название роли не может быть пустым.")
            after[field] = value
    for capability in catalog:
        if capability not in proposed:
            raise ValidationError(f"Не передано право '{capability}' роли '{role_code}'.")
        after[capability] = copy.deepcopy(proposed[capability])
    return after


def _role_definition_changes(*, before, after):
    catalog = capability_catalog()
    changes = []
    for code, label in (("display_name", "Название роли"), ("description", "Описание роли")):
        if before.get(code, "") == after.get(code, ""):
            continue
        changes.append(
            {
                "code": code,
                "label": label,
                "section": "Основные сведения",
                "type": "text",
                "risk": "normal",
                "direction": "metadata",
                "risk_label": "обычный риск",
                "before": str(before.get(code, "")),
                "after": str(after.get(code, "")),
            }
        )
    for capability, metadata in catalog.items():
        if before.get(capability) == after.get(capability):
            continue
        risk = metadata.get("risk", "normal")
        direction = _capability_change_direction(
            capability_type=metadata.get("type", ""),
            before=before.get(capability),
            after=after.get(capability),
        )
        if direction == "reduction" and risk == "normal":
            risk = "elevated"
        changes.append(
            {
                "code": capability,
                "label": metadata.get("label", capability),
                "section": CAPABILITY_GROUP_LABELS.get(
                    capability_group_code(capability, metadata),
                    capability_group_code(capability, metadata),
                ),
                "type": metadata.get("type", ""),
                "risk": risk,
                "direction": direction,
                "risk_label": {"normal": "обычный риск", "elevated": "повышенный риск", "critical": "критический риск"}.get(risk, risk),
                "before": _display_capability_value(before.get(capability)),
                "after": _display_capability_value(after.get(capability)),
            }
        )
    return changes


def _capability_change_direction(*, capability_type, before, after):
    if capability_type == "flag":
        return "reduction" if before is True and after is False else "expansion"
    if capability_type == "targets":
        if before == "*":
            return "reduction"
        if after == "*":
            return "expansion"
        before_set = set(before or [])
        after_set = set(after or [])
        if after_set < before_set:
            return "reduction"
        if after_set > before_set:
            return "expansion"
        return "mixed"
    if capability_type == "scope":
        before_atoms = set(_normalized_scope_atoms([before]))
        after_atoms = set(_normalized_scope_atoms([after]))
        if before_atoms == {"all"}:
            return "reduction"
        if after_atoms == {"all"}:
            return "expansion"
        if after_atoms < before_atoms:
            return "reduction"
        if after_atoms > before_atoms:
            return "expansion"
    return "mixed"


def _role_change_impact(*, role_code, before, after):
    users = list(
        get_user_model().objects.filter(groups__name=role_code)
        .prefetch_related("groups")
        .distinct()
    )
    configs_before = dict(contract_role_configs())
    configs_after = copy.deepcopy(configs_before)
    configs_after[role_code] = after
    effective_change_count = 0
    unchanged_by_other_role_count = 0
    system_override_count = 0
    requires_object_check_count = 0
    changed_scope = any(
        metadata.get("type") == "scope" and before.get(code) != after.get(code)
        for code, metadata in capability_catalog().items()
    )
    for user in users:
        if user.is_superuser:
            system_override_count += 1
            continue
        role_names = [group.name for group in user.groups.all() if group.name in configs_before]
        before_effective = _effective_role_values(role_names, configs_before)
        after_effective = _effective_role_values(role_names, configs_after)
        if before_effective != after_effective:
            effective_change_count += 1
            if changed_scope:
                requires_object_check_count += 1
        else:
            unchanged_by_other_role_count += 1
    return {
        "role_member_count": len(users),
        "unique_affected_user_count": len(users),
        "effective_change_count": effective_change_count,
        "unchanged_by_other_role_count": unchanged_by_other_role_count,
        "system_override_count": system_override_count,
        "requires_object_check_count": requires_object_check_count,
    }


def _effective_role_values(role_names, configs):
    result = {}
    catalog = capability_catalog()
    for capability, metadata in catalog.items():
        if capability in {"transition_scope", "transition_targets"}:
            continue
        values = [configs[role].get(capability) for role in role_names if role in configs]
        capability_type = metadata.get("type")
        if capability_type == "flag":
            result[capability] = any(value is True for value in values)
        elif capability_type == "targets":
            result[capability] = "*" if "*" in values else sorted(
                {item for value in values if isinstance(value, list) for item in value}
            )
        elif capability_type == "scope":
            result[capability] = _normalized_scope_atoms(values)
    # Область перехода и целевой статус образуют одно разрешение. Независимое
    # объединение этих полей создавало несуществующие комбинации между ролями.
    transition_grants = set()
    for role in role_names:
        config = configs.get(role, {})
        scope = config.get("transition_scope", "none")
        targets = config.get("transition_targets", [])
        if scope == "none":
            continue
        if targets == "*":
            transition_grants.add((scope, "*"))
        elif isinstance(targets, list):
            transition_grants.update((scope, target) for target in targets)
    transition_grants = {
        grant
        for grant in transition_grants
        if not any(
            other != grant
            and _transition_grant_subsumes(broad=other, narrow=grant)
            for other in transition_grants
        )
    }
    result["transition_grants"] = sorted(transition_grants)
    return result


def _transition_grant_subsumes(*, broad, narrow):
    broad_scope, broad_target = broad
    narrow_scope, narrow_target = narrow
    target_covers = broad_target == "*" or broad_target == narrow_target
    if not target_covers:
        return False
    if broad_scope in {"all", narrow_scope}:
        return True
    scope_children = {
        "assigned_or_unassigned_or_authored": {
            "assigned_or_unassigned",
            "assigned",
            "authored",
        },
        "assigned_or_unassigned": {"assigned"},
    }
    return narrow_scope in scope_children.get(broad_scope, set())


def _normalized_scope_atoms(values):
    atoms = set()
    mapping = {
        "department_branch": {"department_branch"},
        "assigned_or_unassigned_or_authored": {"assigned", "unassigned", "authored"},
        "assigned_or_unassigned": {"assigned", "unassigned"},
        "visible": {"assigned", "authored"},
        "assigned": {"assigned"},
        "authored": {"authored"},
    }
    for value in values:
        if value == "all":
            return ["all"]
        atoms.update(mapping.get(value, ()))
    return sorted(atoms)


def _load_role_definition_preview(token):
    if not token:
        raise ValidationError("Сначала выполните предпросмотр изменения.")
    try:
        return signing.loads(
            token,
            salt=ROLE_DEFINITION_PREVIEW_SALT,
            max_age=ROLE_DEFINITION_PREVIEW_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise ValidationError("Срок предпросмотра истёк.") from exc
    except signing.BadSignature as exc:
        raise ValidationError("Предпросмотр изменения недействителен.") from exc


def _display_capability_value(value):
    if isinstance(value, bool):
        return "Включено" if value else "Выключено"
    if value == "*":
        return "Все значения"
    if isinstance(value, list):
        return ", ".join(value) if value else "Нет"
    return SCOPE_LABELS.get(value, value)


def _section_label(code):
    return CAPABILITY_GROUP_LABELS.get(code, code)
