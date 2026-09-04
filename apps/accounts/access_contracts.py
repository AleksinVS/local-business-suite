"""Предметный read/preview/apply-контур определений ролей доступа."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count

from apps.core.contract_store import ContractStoreError, get_contract, normalized_hash
from apps.core.file_locks import (
    FileLockTimeoutError,
    access_control_write_lock_path,
    exclusive_file_lock,
)
from apps.workorders.policies import DEFAULT_BOARD_VIEW_ROLE, active_role_rules

from .models import GroupProfile
from .selectors import (
    capability_catalog,
    contract_role_configs,
    role_risk_markers,
)


ROLE_DEFINITION_PREVIEW_SALT = "accounts.role-definition-preview.v1"
ROLE_DEFINITION_PREVIEW_MAX_AGE_SECONDS = 600
ROLE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
RESERVED_ROLE_CODES = frozenset({"superuser", "viewer", DEFAULT_BOARD_VIEW_ROLE})
PROTECTED_CAPABILITIES = frozenset(
    {
        "manage_roles",
        "manage_settings",
        "manage_ai_skills",
        "memory_organization_review",
        "warehouse_adjust_scope",
        "warehouse_manage_catalog",
        "create_waiting_list",
        "waiting_list_view_scope",
        "waiting_list_edit_scope",
        "waiting_list_edit_statuses",
        "waiting_list_transition_scope",
        "waiting_list_transition_from_statuses",
        "waiting_list_transition_targets",
    }
)

SCOPE_LABELS = {
    "all": "Все",
    "own_department": "Только своё подразделение",
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
    "warehouse": "Склад",
    "other": "Прочие права",
}
CAPABILITY_GROUP_DESCRIPTIONS = {
    "memory": "Права памяти организации. Технические группы памяти назначаются отдельно в карточке пользователя.",
    "warehouse": "Права количественного складского учёта с ограничением по подразделениям.",
}
CAPABILITY_RISK_LABELS = {
    "elevated": "Повышенный риск",
    "critical": "Критический риск",
}
ROLE_DEFINITION_EDITOR_DENIED_MESSAGE = (
    "Для управления определениями ролей требуется право manage_roles."
)

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
    "manage_settings": "access",
    "manage_ai_skills": "ai",
    "memory_organization_write": "memory",
    "memory_organization_review": "memory",
    "warehouse_view_scope": "warehouse",
    "warehouse_operate_scope": "warehouse",
    "warehouse_adjust_scope": "warehouse",
    "warehouse_manage_locations_scope": "warehouse",
    "warehouse_manage_report_profiles_scope": "warehouse",
    "warehouse_manage_catalog": "warehouse",
    "waiting_list_view_scope": "waiting_list",
    "waiting_list_edit_scope": "waiting_list",
    "waiting_list_edit_statuses": "waiting_list",
    "waiting_list_transition_scope": "waiting_list",
    "waiting_list_transition_from_statuses": "waiting_list",
    "waiting_list_transition_targets": "waiting_list",
}


def _role_rules_snapshot(*, fresh=False):
    """Вернуть единый transport-снимок роли для CAS hash + revision."""

    from apps.settings_center.contract_services import read_contract_snapshot
    from apps.settings_center.registry import get_registry

    return read_contract_snapshot(
        get_registry().get("core.contract.role_rules"),
        fresh=fresh,
    )


def _assert_role_form_version(*, snapshot, base_hash, base_revision=None):
    if snapshot.content_hash != str(base_hash or "").removeprefix("sha256:"):
        raise ValidationError("Контракт ролей уже изменился. Перезагрузите страницу.")
    if snapshot.source not in {"database_override", "git_default"}:
        return
    if base_revision is None:
        raise ValidationError("Не указана ревизия контракта ролей. Перезагрузите страницу.")
    try:
        requested_revision = int(base_revision)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Ревизия контракта ролей имеет неверный формат.") from exc
    if requested_revision != snapshot.revision:
        raise ValidationError("Контракт ролей уже изменился. Перезагрузите страницу.")


def can_edit_role_definitions(actor, *, rules_snapshot=None):
    """Return whether an active actor has product role-definition authority."""
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        return False
    current = get_user_model().objects.filter(pk=actor.pk, is_active=True).first()
    if not current:
        return False
    if current.is_superuser:
        return True
    try:
        if isinstance(rules_snapshot, dict):
            rules = rules_snapshot
        else:
            from apps.settings_center.document_registry import get_document_registry

            if (
                get_document_registry()
                .get("core.contract.role_rules")
                .active_backend
                == "database"
            ):
                from apps.settings_center.document_repository import get_fresh_document

                rules = get_fresh_document("core.contract.role_rules").payload
            else:
                # A legacy sandbox may intentionally contain only the role
                # file; loading a connected DB scope here would manufacture a
                # false repository failure for the legacy backend.
                rules = get_contract("role_rules")
        return any(
            rule.get("manage_roles") is True
            for rule in active_role_rules(current, rules_payload=rules)
        )
    except (ContractStoreError, ValidationError, TypeError, ValueError):
        return False


def role_is_protected(config, *, catalog=None) -> bool:
    """Return effective protected state; malformed security data fails closed."""

    if not isinstance(config, dict):
        return True
    explicit = config.get("protected", False)
    if type(explicit) is not bool:
        return True
    if explicit:
        return True
    if catalog is None:
        try:
            catalog = capability_catalog()
        except Exception:
            return True
    if not isinstance(catalog, dict):
        return True
    for code in PROTECTED_CAPABILITIES:
        metadata = catalog.get(code)
        # A validated legacy catalog may predate a newly released capability.
        # Such a capability is absent from every role and its consumer resolves
        # to the safe default, so it must not turn all legacy roles into
        # protected roles during the reviewed catalog migration.  Once the
        # catalog declares the capability, a missing or malformed role value
        # remains fail-closed.
        if metadata is None and code not in catalog:
            continue
        if not isinstance(metadata, dict) or code not in config:
            return True
        effective = _strict_capability_effective(
            code=code,
            metadata=metadata,
            value=config.get(code),
            catalog=catalog,
        )
        if effective is None or effective:
            return True
    return False


def _strict_capability_effective(*, code, metadata, value, catalog):
    capability_type = metadata.get("type")
    if capability_type == "flag":
        return value if type(value) is bool else None
    if capability_type not in {"scope", "targets"}:
        return None
    try:
        from apps.workorders.contracts import capability_values, resolve_capability_values_source

        source = resolve_capability_values_source(code, metadata, metadata=catalog)
        allowed = set(capability_values(source, workflow_payload=get_contract("workflow_rules")))
    except Exception:
        return None
    if capability_type == "scope":
        if not isinstance(value, str) or value not in allowed:
            return None
        return value != "none"
    if value == "*":
        return True if "*" in allowed else None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return None
    if len(value) != len(set(value)):
        return None
    if "*" in value or any(item not in allowed for item in value):
        return None
    return bool(value)


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
    catalog = capability_catalog()
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
            "protected": role_is_protected(config, catalog=catalog),
        })
    return rows


def role_definition_read_model(role_code):
    snapshot = _role_rules_snapshot()
    rules = snapshot.payload
    config = rules.get(role_code)
    if not isinstance(config, dict) or role_code.startswith("$"):
        raise ValidationError("Роль не найдена.")
    catalog = rules.get("$capabilities", {})
    if not isinstance(catalog, dict):
        catalog = {}
    from apps.workorders.contracts import resolve_capability_values_source
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
                    "values_source": resolve_capability_values_source(
                        code,
                        metadata,
                        metadata=catalog,
                    ) if metadata.get("type") in {"scope", "targets"} else None,
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
        "protected": role_is_protected(config, catalog=catalog),
        "explicit_protected": config.get("protected", False) is True,
        "config": copy.deepcopy(config),
        "sections": sections,
        "member_count": get_user_model().objects.filter(groups__name=role_code).distinct().count(),
        "base_hash": snapshot.content_hash,
        "base_revision": snapshot.revision,
    }


def preview_role_definition_change(
    *, actor, role_code, proposed_config, base_hash, base_revision=None
):
    snapshot = _role_rules_snapshot()
    rules = snapshot.payload
    actor = _require_role_definition_editor(actor, rules_snapshot=rules)
    _assert_role_form_version(
        snapshot=snapshot,
        base_hash=base_hash,
        base_revision=base_revision,
    )
    before = rules.get(role_code)
    if not isinstance(before, dict) or role_code.startswith("$"):
        raise ValidationError("Роль не найдена.")
    catalog = rules.get("$capabilities", {})
    if not isinstance(catalog, dict):
        catalog = {}
    after = _normalize_proposed_role(
        role_code=role_code,
        before=before,
        proposed=proposed_config,
        catalog=catalog,
    )
    if before == after:
        raise ValidationError("В роли нет изменений для проверки.")

    candidate = copy.deepcopy(rules)
    candidate[role_code] = after
    from apps.settings_center.contract_services import parse_and_validate_payload
    from apps.settings_center.registry import get_registry

    descriptor = get_registry().get("core.contract.role_rules")
    parse_and_validate_payload(descriptor, json.dumps(candidate, ensure_ascii=False))
    changes = _role_definition_changes(before=before, after=after, catalog=catalog)
    _assert_role_definition_target_policy(
        actor=actor,
        role_code=role_code,
        before=before,
        after=after,
        rules_snapshot=rules,
    )
    impact = _role_change_impact(
        role_code=role_code,
        before=before,
        after=after,
        rules_snapshot=rules,
    )
    risk_markers = [
        f"{change['label']}: {change['risk_label']}"
        for change in changes
        if change["risk"] in {"elevated", "critical"}
    ]
    token_payload = {
        "actor_id": actor.pk,
        "actor_state": _role_editor_actor_state(actor, rules_snapshot=rules),
        "role_code": role_code,
        "base_hash": snapshot.content_hash,
        "payload_hash": normalized_hash(rules),
        "base_revision": snapshot.revision,
        "after": after,
        "member_fingerprint": _role_member_fingerprint(role_code),
        "impact_hash": normalized_hash(impact),
        "nonce": str(uuid.uuid4()),
    }
    return {
        "role": {"code": role_code, "label": after.get("display_name", role_code)},
        "base_hash": snapshot.content_hash,
        "base_revision": snapshot.revision,
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
    *,
    actor,
    role_code,
    proposed_config,
    base_hash,
    preview_token,
    risk_confirmed=False,
    base_revision=None,
):
    signed = _load_role_definition_preview(preview_token)
    snapshot = _role_rules_snapshot(fresh=True)
    rules = snapshot.payload
    actor = _require_role_definition_editor(actor, rules_snapshot=rules)
    if signed.get("actor_id") != actor.pk or signed.get("role_code") != role_code:
        raise ValidationError("Предпросмотр относится к другой роли или администратору.")
    if signed.get("actor_state") != _role_editor_actor_state(actor, rules_snapshot=rules):
        raise ValidationError("Права администратора изменились после предпросмотра.")
    if signed.get("base_hash") != str(base_hash or "").removeprefix("sha256:"):
        raise ValidationError("Версия формы не совпадает с предпросмотром.")
    if signed.get("base_revision", 0) != snapshot.revision:
        raise ValidationError("Ревизия контракта изменилась после предпросмотра.")
    if snapshot.source in {"database_override", "git_default"}:
        try:
            requested_revision = int(base_revision)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Ревизия контракта ролей имеет неверный формат.") from exc
        if requested_revision != snapshot.revision:
            raise ValidationError("Версия формы не совпадает с предпросмотром.")
    if normalized_hash(rules) != signed.get("payload_hash", signed.get("base_hash")):
        raise ValidationError("Контракт ролей изменился после предпросмотра.")
    before = rules.get(role_code)
    catalog = rules.get("$capabilities", {})
    if not isinstance(catalog, dict):
        catalog = {}
    after = _normalize_proposed_role(
        role_code=role_code,
        before=before,
        proposed=proposed_config,
        catalog=catalog,
    )
    if signed.get("after") != after:
        raise ValidationError("Поля роли изменились после предпросмотра.")
    changes = _role_definition_changes(before=before, after=after, catalog=catalog)
    _assert_role_definition_target_policy(
        actor=actor,
        role_code=role_code,
        before=before,
        after=after,
        rules_snapshot=rules,
    )
    impact = _role_change_impact(
        role_code=role_code,
        before=before,
        after=after,
        rules_snapshot=rules,
    )
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
    from apps.settings_center.contract_services import _apply_role_definition_payload

    preview_fingerprint = hashlib.sha256(preview_token.encode("utf-8")).hexdigest()

    def locked_precondition(current_actor, current_rules):
        if normalized_hash(current_rules) != signed.get(
            "payload_hash", signed.get("base_hash")
        ):
            raise ValidationError("Контракт ролей изменился после предпросмотра.")
        current_actor = _require_role_definition_editor(
            current_actor,
            rules_snapshot=current_rules,
        )
        if signed.get("actor_state") != _role_editor_actor_state(
            current_actor,
            rules_snapshot=current_rules,
        ):
            raise ValidationError("Права администратора изменились после предпросмотра.")
        current_before = current_rules.get(role_code)
        current_catalog = current_rules.get("$capabilities", {})
        if not isinstance(current_before, dict) or not isinstance(current_catalog, dict):
            raise ValidationError("Роль исчезла или стала некорректной.")
        current_after = _normalize_proposed_role(
            role_code=role_code,
            before=current_before,
            proposed=proposed_config,
            catalog=current_catalog,
        )
        current_changes = _role_definition_changes(
            before=current_before,
            after=current_after,
            catalog=current_catalog,
        )
        _assert_role_definition_target_policy(
            actor=current_actor,
            role_code=role_code,
            before=current_before,
            after=current_after,
            rules_snapshot=current_rules,
        )
        current_impact = _role_change_impact(
            role_code=role_code,
            before=current_before,
            after=current_after,
            rules_snapshot=current_rules,
        )
        if signed.get("member_fingerprint") != _role_member_fingerprint(role_code) or signed.get(
            "impact_hash"
        ) != normalized_hash(current_impact):
            raise ValidationError(
                "Состав участников роли или влияние изменения изменились. "
                "Выполните предпросмотр снова."
            )

    def raw_payload_factory(current_rules):
        current_before = current_rules.get(role_code)
        current_catalog = current_rules.get("$capabilities", {})
        if not isinstance(current_before, dict) or not isinstance(current_catalog, dict):
            raise ValidationError("Роль исчезла или стала некорректной.")
        current_after = _normalize_proposed_role(
            role_code=role_code,
            before=current_before,
            proposed=proposed_config,
            catalog=current_catalog,
        )
        if current_after != after:
            raise ValidationError("Поля роли изменились после предпросмотра.")
        candidate = copy.deepcopy(current_rules)
        candidate[role_code] = current_after
        return json.dumps(candidate, ensure_ascii=False)

    return _apply_role_definition_payload(
        actor=actor,
        role_code=role_code,
        confirmed=True,
        base_hash=signed["base_hash"],
        base_revision=signed.get("base_revision", 0),
        preview_token=preview_token,
        risk_confirmed=risk_confirmed,
        operation_fingerprint=preview_fingerprint,
        raw_payload_factory=raw_payload_factory,
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


def save_role_definition_change(
    *, actor, role_code, proposed_config, base_hash, base_revision=None
):
    """Проверить и сразу применить определение одной роли.

    ``base_hash`` остаётся optimistic-lock открытой формы. Подписанный
    план создаётся и потребляется внутри одного серверного вызова;
    браузер не участвует в preview/apply-протоколе.
    """

    preview = preview_role_definition_change(
        actor=actor,
        role_code=role_code,
        proposed_config=proposed_config,
        base_hash=base_hash,
        base_revision=base_revision,
    )
    return apply_role_definition_change(
        actor=actor,
        role_code=role_code,
        proposed_config=proposed_config,
        base_hash=preview["base_hash"],
        base_revision=preview["base_revision"],
        preview_token=preview["preview_token"],
        risk_confirmed=True,
    )


def save_role_creation(
    *,
    actor,
    role_code,
    display_name,
    description="",
    protected=False,
    base_hash,
    base_revision=None,
):
    """Create one least-privilege role after reserving its Django group.

    The empty predefined Group is materialized under the access lock before
    the contract can make its name authoritative. A hard process stop can
    therefore leave only an inert orphan Group, never an active role backed by
    an unrelated technical or AD group.
    """

    snapshot = _role_rules_snapshot()
    rules = snapshot.payload
    actor = _require_role_definition_editor(actor, rules_snapshot=rules)
    _assert_role_form_version(
        snapshot=snapshot,
        base_hash=base_hash,
        base_revision=base_revision,
    )
    role_code = _normalize_new_role_code(role_code)
    catalog = rules.get("$capabilities")
    if not isinstance(catalog, dict):
        raise ValidationError("Справочник прав роли некорректен.")
    after = _new_role_config(
        role_code=role_code,
        display_name=display_name,
        description=description,
        protected=protected,
        catalog=catalog,
    )
    existing = rules.get(role_code)
    if existing is not None:
        if existing == after:
            _assert_role_definition_target_policy(
                actor=actor,
                role_code=role_code,
                before=None,
                after=after,
                rules_snapshot=rules,
            )
            _repair_role_materialization(
                actor=actor,
                role_code=role_code,
                expected_config=after,
                expected_hash=snapshot.content_hash,
                expected_revision=snapshot.revision,
            )
            return None
        raise ValidationError("Роль с таким кодом уже существует.")
    _assert_new_role_code_available(
        role_code=role_code,
        rules_snapshot=rules,
        expected_config=after,
    )
    _assert_role_definition_target_policy(
        actor=actor,
        role_code=role_code,
        before=None,
        after=after,
        rules_snapshot=rules,
    )
    signed_payload = {
        "action": "create",
        "actor_id": actor.pk,
        "actor_state": _role_editor_actor_state(actor, rules_snapshot=rules),
        "role_code": role_code,
        "base_hash": snapshot.content_hash,
        "payload_hash": normalized_hash(rules),
        "base_revision": snapshot.revision,
        "after": after,
        "member_fingerprint": _role_member_fingerprint(role_code),
        "nonce": str(uuid.uuid4()),
    }
    preview_token = signing.dumps(
        signed_payload,
        salt=ROLE_DEFINITION_PREVIEW_SALT,
        compress=True,
    )

    def locked_precondition(current_actor, current_rules):
        if normalized_hash(current_rules) != signed_payload["payload_hash"]:
            raise ValidationError("Контракт ролей изменился после предпросмотра.")
        current_actor = _require_role_definition_editor(
            current_actor, rules_snapshot=current_rules
        )
        if signed_payload["actor_state"] != _role_editor_actor_state(
            current_actor, rules_snapshot=current_rules
        ):
            raise ValidationError("Права администратора изменились после предпросмотра.")
        _assert_new_role_code_available(
            role_code=role_code,
            rules_snapshot=current_rules,
            expected_config=after,
        )
        _assert_role_definition_target_policy(
            actor=current_actor,
            role_code=role_code,
            before=None,
            after=after,
            rules_snapshot=current_rules,
        )

    def raw_payload_factory(current_rules):
        candidate = copy.deepcopy(current_rules)
        candidate[role_code] = copy.deepcopy(after)
        return json.dumps(candidate, ensure_ascii=False)

    def pre_write_callback(_current_actor, written_rules):
        _materialize_role_group(
            role_code,
            written_rules[role_code],
            require_new=True,
            allow_inert_reservation=True,
        )

    from apps.settings_center.contract_services import _apply_role_definition_payload

    change = _apply_role_definition_payload(
        actor=actor,
        role_code=role_code,
        confirmed=True,
        base_hash=signed_payload["base_hash"],
        base_revision=signed_payload["base_revision"],
        preview_token=preview_token,
        risk_confirmed=True,
        operation_fingerprint=hashlib.sha256(preview_token.encode("utf-8")).hexdigest(),
        raw_payload_factory=raw_payload_factory,
        locked_precondition=locked_precondition,
        pre_write_callback=pre_write_callback,
        audit_context={
            "source": "role_definition_creator",
            "role_code": role_code,
            "protected": role_is_protected(after, catalog=catalog),
        },
    )
    return change


def save_role_copy(
    *,
    actor,
    source_role_code,
    target_role_code,
    display_name,
    description="",
    base_hash,
    base_revision=None,
):
    """Create a flat copy of one role definition, without assignments."""
    snapshot = _role_rules_snapshot()
    rules = snapshot.payload
    actor = _require_role_definition_editor(actor, rules_snapshot=rules)
    _assert_role_form_version(
        snapshot=snapshot,
        base_hash=base_hash,
        base_revision=base_revision,
    )
    source_role_code = str(source_role_code or "").strip()
    source = rules.get(source_role_code)
    if source_role_code.startswith("$") or not isinstance(source, dict):
        raise ValidationError("Исходная роль не найдена.")
    target_role_code = _normalize_new_role_code(target_role_code)
    catalog = rules.get("$capabilities", {})
    if not isinstance(catalog, dict):
        raise ValidationError("Справочник прав роли некорректен.")
    copied = copy.deepcopy(source)
    copied["display_name"] = str(display_name or "").strip()
    copied["description"] = str(description or "").strip()
    if not copied["display_name"]:
        raise ValidationError("Название роли не может быть пустым.")
    _assert_new_role_code_available(
        role_code=target_role_code, rules_snapshot=rules, expected_config=copied
    )
    if not actor.is_superuser and role_is_protected(source, catalog=catalog):
        raise PermissionDenied(
            "Защищённую роль может копировать только активный суперпользователь."
        )
    _assert_role_definition_target_policy(
        actor=actor,
        role_code=target_role_code,
        before=None,
        after=copied,
        rules_snapshot=rules,
    )
    source_hash = normalized_hash(source)
    signed_payload = {
        "action": "copy",
        "actor_id": actor.pk,
        "actor_state": _role_editor_actor_state(actor, rules_snapshot=rules),
        "role_code": target_role_code,
        "source_role_code": source_role_code,
        "source_role_hash": source_hash,
        "base_hash": snapshot.content_hash,
        "payload_hash": normalized_hash(rules),
        "base_revision": snapshot.revision,
        "after": copied,
        "member_fingerprint": _role_member_fingerprint(target_role_code),
        "nonce": str(uuid.uuid4()),
    }
    preview_token = signing.dumps(
        signed_payload, salt=ROLE_DEFINITION_PREVIEW_SALT, compress=True
    )

    def locked_precondition(current_actor, current_rules):
        if normalized_hash(current_rules) != signed_payload["payload_hash"]:
            raise ValidationError("Контракт ролей изменился после предпросмотра.")
        current_actor = _require_role_definition_editor(
            current_actor, rules_snapshot=current_rules
        )
        if signed_payload["actor_state"] != _role_editor_actor_state(
            current_actor, rules_snapshot=current_rules
        ):
            raise ValidationError("Права администратора изменились после предпросмотра.")
        current_source = current_rules.get(source_role_code)
        if not isinstance(current_source, dict) or normalized_hash(current_source) != source_hash:
            raise ValidationError("Исходная роль изменилась после предпросмотра.")
        _assert_new_role_code_available(
            role_code=target_role_code,
            rules_snapshot=current_rules,
            expected_config=copied,
        )
        current_catalog = current_rules.get("$capabilities", {})
        if not current_actor.is_superuser and role_is_protected(current_source, catalog=current_catalog):
            raise PermissionDenied(
                "Защищённую роль может копировать только активный суперпользователь."
            )
        _assert_role_definition_target_policy(
            actor=current_actor,
            role_code=target_role_code,
            before=None,
            after=copied,
            rules_snapshot=current_rules,
        )

    def raw_payload_factory(current_rules):
        candidate = copy.deepcopy(current_rules)
        candidate[target_role_code] = copy.deepcopy(copied)
        return json.dumps(candidate, ensure_ascii=False)

    def pre_write_callback(_current_actor, written_rules):
        _materialize_role_group(
            target_role_code,
            written_rules[target_role_code],
            require_new=True,
            allow_inert_reservation=True,
        )

    from apps.settings_center.contract_services import _apply_role_definition_payload

    return _apply_role_definition_payload(
        actor=actor,
        role_code=target_role_code,
        confirmed=True,
        base_hash=signed_payload["base_hash"],
        base_revision=signed_payload["base_revision"],
        preview_token=preview_token,
        risk_confirmed=True,
        operation_fingerprint=hashlib.sha256(preview_token.encode("utf-8")).hexdigest(),
        raw_payload_factory=raw_payload_factory,
        locked_precondition=locked_precondition,
        pre_write_callback=pre_write_callback,
        audit_context={
            "source": "role_definition_copy",
            "source_role_code": source_role_code,
            "target_role_code": target_role_code,
            "source_role_hash": source_hash,
        },
    )


def _normalize_new_role_code(value):
    code = str(value or "").strip()
    if not ROLE_CODE_PATTERN.fullmatch(code):
        raise ValidationError(
            "Код роли должен начинаться со строчной латинской буквы и содержать "
            "только строчные буквы, цифры и подчёркивание."
        )
    if code in RESERVED_ROLE_CODES:
        raise ValidationError("Этот код роли зарезервирован системой.")
    return code


def _is_inert_role_group_reservation(group, config):
    profile = GroupProfile.objects.filter(group=group).first()
    return bool(
        profile is not None
        and profile.is_predefined
        and profile.title == str(config.get("display_name", ""))
        and profile.description == str(config.get("description", ""))
        and not group.user_set.exists()
        and not group.permissions.exists()
    )


def _assert_new_role_code_available(
    *, role_code, rules_snapshot, expected_config=None
):
    if role_code in rules_snapshot:
        raise ValidationError("Роль с таким кодом уже существует.")
    from apps.memory.policies import MEMORY_REVIEW_GROUP_PROFILES

    if role_code in MEMORY_REVIEW_GROUP_PROFILES:
        raise ValidationError("Код роли совпадает с технической группой памяти.")
    group = Group.objects.filter(name=role_code).first()
    if group is not None and not (
        isinstance(expected_config, dict)
        and _is_inert_role_group_reservation(group, expected_config)
    ):
        raise ValidationError(
            "Код роли совпадает с существующей технической или AD-группой."
        )


def _new_role_config(*, role_code, display_name, description, protected, catalog):
    display_name = str(display_name or "").strip()
    description = str(description or "").strip()
    if not display_name:
        raise ValidationError("Название роли не может быть пустым.")
    if type(protected) is not bool:
        raise ValidationError("Признак защищённой роли должен быть логическим значением.")
    config = {
        "display_name": display_name,
        "description": description,
        "protected": protected,
    }
    for code, metadata in catalog.items():
        if not isinstance(metadata, dict):
            raise ValidationError(f"Описание права '{code}' некорректно.")
        capability_type = metadata.get("type")
        if capability_type == "flag":
            config[code] = False
        elif capability_type == "targets":
            config[code] = []
        elif capability_type == "scope":
            from apps.workorders.contracts import capability_values, resolve_capability_values_source

            source = resolve_capability_values_source(code, metadata, metadata=catalog)
            values = capability_values(source, workflow_payload=get_contract("workflow_rules"))
            if "none" not in values:
                raise ValidationError(
                    f"Для права '{code}' нельзя построить закрытое значение новой роли."
                )
            config[code] = "none"
        else:
            raise ValidationError(f"Неизвестный тип права '{code}'.")
    return config


@transaction.atomic
def _materialize_role_group(
    role_code,
    config,
    *,
    require_new=False,
    allow_inert_reservation=False,
):
    group, created = Group.objects.get_or_create(name=role_code)
    if require_new and not created:
        group = Group.objects.select_for_update().get(pk=group.pk)
        if not (
            allow_inert_reservation
            and _is_inert_role_group_reservation(group, config)
        ):
            raise ValidationError(
                "Группа с кодом роли занята технической или AD-группой (гонка создания)."
            )
    if not created:
        profile = GroupProfile.objects.select_for_update().filter(group=group).first()
        expected_title = str(config.get("display_name", ""))
        expected_description = str(config.get("description", ""))
        if (
            profile is None
            or not profile.is_predefined
            or profile.title != expected_title
            or profile.description != expected_description
        ):
            raise ValidationError(
                "Группа с кодом роли занята технической или AD-группой."
            )
    GroupProfile.objects.update_or_create(
        group=group,
        defaults={
            "title": str(config.get("display_name", "")),
            "description": str(config.get("description", "")),
            "is_predefined": True,
        },
    )
    return group


def _repair_role_materialization(
    *, actor, role_code, expected_config, expected_hash, expected_revision
):
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            # The request-local snapshot is deliberately not authoritative once
            # the access lock is acquired.  A concurrent DB writer may have
            # advanced the role document between the initial read and this
            # repair path; materialising the stale role would create an
            # untracked access definition.
            from apps.settings_center.document_repository import get_fresh_document
            from apps.settings_center.document_registry import get_document_registry

            role_spec = get_document_registry().get("core.contract.role_rules")
            if role_spec.active_backend == "database":
                current = get_fresh_document("core.contract.role_rules")
            else:
                # Legacy deployments can intentionally provide only the role
                # file (for example during deployment migration).  Keep the
                # same no-cache semantics without forcing a connected DB
                # scope whose Git dependency is absent in that sandbox.
                current = _role_rules_snapshot(fresh=True)
            rules = current.payload
            actor = _require_role_definition_editor(actor, rules_snapshot=rules)
            if (
                current.content_hash != expected_hash
                or current.revision != expected_revision
                or rules.get(role_code) != expected_config
            ):
                raise ValidationError("Контракт роли изменился; повторите операцию.")
            _assert_role_definition_target_policy(
                actor=actor,
                role_code=role_code,
                before=None,
                after=expected_config,
                rules_snapshot=rules,
            )
            return _materialize_role_group(role_code, expected_config)
    except FileLockTimeoutError as exc:
        raise ValidationError("Доступ сейчас изменяет другой процесс. Повторите позже.") from exc


def _require_role_definition_editor(actor, *, rules_snapshot=None):
    if not getattr(actor, "is_authenticated", False):
        raise PermissionDenied("Требуется вход в систему.")
    rules = rules_snapshot if isinstance(rules_snapshot, dict) else get_contract("role_rules")
    if not can_edit_role_definitions(actor, rules_snapshot=rules):
        raise PermissionDenied(ROLE_DEFINITION_EDITOR_DENIED_MESSAGE)
    current = get_user_model().objects.get(pk=actor.pk)
    return current


def _role_editor_actor_state(actor, *, rules_snapshot=None):
    rules = rules_snapshot if isinstance(rules_snapshot, dict) else get_contract("role_rules")
    return {
        "is_active": bool(actor.is_active),
        "is_superuser": bool(actor.is_superuser),
        "roles": sorted(actor.groups.values_list("name", flat=True)),
        "can_manage_roles": any(
            rule.get("manage_roles") is True
            for rule in active_role_rules(actor, rules_payload=rules)
        ),
    }


def _assert_role_definition_target_policy(
    *, actor, role_code, before, after, rules_snapshot
):
    """Enforce held-role and protected-before-or-after boundaries."""
    # ``viewer`` is a migration-owned frozen role.  Its contract value is
    # intentionally ``protected=false`` so the catalog describes its
    # least-privilege nature, but ordinary role writers must not edit it after
    # cutover or turn it into a second privilege-escalation path.
    if role_code == "viewer":
        raise PermissionDenied("Роль viewer изменяется только dedicated migration service.")
    if actor.is_superuser:
        return
    held_roles = {
        group.name
        for group in actor.groups.all()
        if group.name in {
            name
            for name, config in rules_snapshot.items()
            if isinstance(name, str) and not name.startswith("$") and isinstance(config, dict)
        }
    }
    if role_code in held_roles:
        raise PermissionDenied(
            "Делегированный редактор не может изменять определение роли, которой сам обладает."
        )
    catalog = rules_snapshot.get("$capabilities")
    if (
        (before is not None and role_is_protected(before, catalog=catalog))
        or role_is_protected(after, catalog=catalog)
    ):
        raise PermissionDenied(
            "Защищённую роль может создавать или изменять только активный суперпользователь."
        )


def _validate_role_definition_transport_request(
    *, actor, role_code, before, after, preview_token, risk_confirmed
):
    """Independent under-lock validation for the constrained write transport."""
    signed = _load_role_definition_preview(preview_token)
    if signed.get("actor_id") != actor.pk or signed.get("role_code") != role_code:
        raise PermissionDenied("Предпросмотр относится к другой роли или администратору.")
    if signed.get("payload_hash", signed.get("base_hash")) != normalized_hash(before):
        raise ValidationError("Контракт ролей изменился после предпросмотра.")
    action = signed.get("action", "edit")
    current_before = before.get(role_code)
    current_after = after.get(role_code)
    if action in {"create", "copy"}:
        if current_before is not None or not isinstance(current_after, dict):
            raise ValidationError("Новая роль уже существует или стала некорректной.")
    elif not isinstance(current_before, dict) or not isinstance(current_after, dict):
        raise ValidationError("Роль исчезла или стала некорректной.")
    if signed.get("after") != current_after:
        raise ValidationError("Поля роли изменились после предпросмотра.")
    actor = _require_role_definition_editor(actor, rules_snapshot=before)
    if signed.get("actor_state") != _role_editor_actor_state(actor, rules_snapshot=before):
        raise ValidationError("Права администратора изменились после предпросмотра.")
    catalog = before.get("$capabilities", {})
    _assert_role_definition_target_policy(
        actor=actor,
        role_code=role_code,
        before=current_before,
        after=current_after,
        rules_snapshot=before,
    )
    if action == "copy":
        source_role_code = signed.get("source_role_code")
        source = before.get(source_role_code)
        if not isinstance(source, dict) or signed.get("source_role_hash") != normalized_hash(source):
            raise ValidationError("Исходная роль изменилась после предпросмотра.")
    if action in {"create", "copy"}:
        _assert_new_role_code_available(
            role_code=role_code,
            rules_snapshot=before,
            expected_config=current_after,
        )
        if signed.get("member_fingerprint") != _role_member_fingerprint(role_code):
            raise ValidationError("Состав участников новой роли изменился.")
        return
    changes = _role_definition_changes(
        before=current_before,
        after=current_after,
        catalog=catalog,
    )
    impact = _role_change_impact(
        role_code=role_code,
        before=current_before,
        after=current_after,
        rules_snapshot=before,
    )
    if signed.get("member_fingerprint") != _role_member_fingerprint(role_code):
        raise ValidationError("Состав участников роли изменился. Выполните предпросмотр снова.")
    if signed.get("impact_hash") != normalized_hash(impact):
        raise ValidationError("Влияние изменения изменилось. Выполните предпросмотр снова.")
    if any(change["risk"] in {"elevated", "critical"} for change in changes) and not risk_confirmed:
        raise ValidationError("Изменение чувствительных прав требует подтверждения.")


def _role_member_fingerprint(role_code):
    member_ids = list(
        get_user_model().objects.filter(groups__name=role_code)
        .order_by("pk")
        .values_list("pk", flat=True)
        .distinct()
    )
    return normalized_hash(member_ids)


def _normalize_proposed_role(*, role_code, before, proposed, catalog):
    if not isinstance(before, dict) or not isinstance(proposed, dict):
        raise ValidationError("Некорректное определение роли.")
    metadata_fields = {"display_name", "description", "protected"}
    unknown = sorted(set(proposed) - set(catalog) - metadata_fields)
    if unknown:
        raise ValidationError(
            "Переданы неизвестные права роли: " + ", ".join(unknown) + "."
        )
    after = copy.deepcopy(before)
    for field in {"display_name", "description"}:
        if field in proposed:
            value = str(proposed[field] or "").strip()
            if field == "display_name" and not value:
                raise ValidationError("Название роли не может быть пустым.")
            after[field] = value
    if "protected" in proposed:
        if type(proposed["protected"]) is not bool:
            raise ValidationError("Признак защищённой роли должен быть логическим значением.")
        after["protected"] = proposed["protected"]
    for capability in catalog:
        if capability not in proposed:
            raise ValidationError(f"Не передано право '{capability}' роли '{role_code}'.")
        after[capability] = copy.deepcopy(proposed[capability])
    return after


def _role_definition_changes(*, before, after, catalog):
    changes = []
    if before.get("protected", False) is not after.get("protected", False):
        changes.append(
            {
                "code": "protected",
                "label": "Защищённая роль",
                "section": "Основные сведения",
                "type": "flag",
                "risk": "critical",
                "direction": "expansion" if after.get("protected") is True else "reduction",
                "risk_label": "критический риск",
                "before": before.get("protected", False),
                "after": after.get("protected", False),
            }
        )
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
        before_atoms = _scope_direction_atoms(before)
        after_atoms = _scope_direction_atoms(after)
        if before_atoms == {"all"}:
            return "reduction"
        if after_atoms == {"all"}:
            return "expansion"
        if after_atoms < before_atoms:
            return "reduction"
        if after_atoms > before_atoms:
            return "expansion"
    return "mixed"


def _scope_direction_atoms(value):
    """Use opaque scope atoms for security direction; incomparable is mixed."""
    if value == "all":
        return {"all"}
    if value == "none":
        return set()
    return {value}


def _role_change_impact(*, role_code, before, after, rules_snapshot=None):
    users = list(
        get_user_model().objects.filter(groups__name=role_code)
        .prefetch_related("groups")
        .distinct()
    )
    snapshot = rules_snapshot if isinstance(rules_snapshot, dict) else get_contract("role_rules")
    configs_before = {
        code: dict(config)
        for code, config in snapshot.items()
        if isinstance(code, str) and not code.startswith("$") and isinstance(config, dict)
    }
    catalog = snapshot.get("$capabilities", {})
    if not isinstance(catalog, dict):
        catalog = {}
    configs_after = copy.deepcopy(configs_before)
    configs_after[role_code] = after
    effective_change_count = 0
    unchanged_by_other_role_count = 0
    system_override_count = 0
    requires_object_check_count = 0
    changed_scope = any(
        metadata.get("type") == "scope" and before.get(code) != after.get(code)
        for code, metadata in catalog.items()
    )
    for user in users:
        if user.is_superuser:
            system_override_count += 1
            continue
        role_names = [group.name for group in user.groups.all() if group.name in configs_before]
        before_effective = _effective_role_values(role_names, configs_before, catalog=catalog)
        after_effective = _effective_role_values(role_names, configs_after, catalog=catalog)
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


def _effective_role_values(role_names, configs, *, catalog=None):
    result = {}
    catalog = catalog if isinstance(catalog, dict) else capability_catalog()
    for capability, metadata in catalog.items():
        if capability in {
            "transition_scope",
            "transition_targets",
            "waiting_list_edit_scope",
            "waiting_list_edit_statuses",
            "waiting_list_transition_scope",
            "waiting_list_transition_from_statuses",
            "waiting_list_transition_targets",
        }:
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

    # Scope and status lists are one grant.  Build combinations only inside a
    # single role so one role's broad scope cannot be combined with another
    # role's statuses into a permission neither role actually grants.
    edit_grants = set()
    transition_grants = set()
    for role in role_names:
        config = configs.get(role, {})
        edit_scope = config.get("waiting_list_edit_scope", "none")
        edit_statuses = config.get("waiting_list_edit_statuses", [])
        if edit_scope != "none":
            statuses = ["*"] if edit_statuses == "*" else edit_statuses
            edit_grants.update((edit_scope, status) for status in statuses)
        transition_scope = config.get("waiting_list_transition_scope", "none")
        from_statuses = config.get("waiting_list_transition_from_statuses", [])
        targets = config.get("waiting_list_transition_targets", [])
        if transition_scope != "none":
            sources = ["*"] if from_statuses == "*" else from_statuses
            destinations = ["*"] if targets == "*" else targets
            transition_grants.update(
                (transition_scope, source, destination)
                for source in sources
                for destination in destinations
            )
    result["waiting_list_edit_grants"] = sorted(edit_grants)
    result["waiting_list_transition_grants"] = sorted(transition_grants)
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
