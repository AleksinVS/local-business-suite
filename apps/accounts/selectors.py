from __future__ import annotations

import json
from collections import OrderedDict

from django.contrib.auth.models import Permission

from apps.core.contract_store import get_contract
from apps.workorders.policies import (
    DEFAULT_BOARD_VIEW_ROLE,
    default_board_access_applies,
    default_board_view_rules,
)


RISK_LABELS = {"elevated": "повышенный риск", "critical": "критический риск"}


def contract_role_configs() -> OrderedDict[str, dict]:
    rules = get_contract("role_rules")
    return OrderedDict(
        (name, dict(config))
        for name, config in rules.items()
        if isinstance(name, str) and not name.startswith("$") and isinstance(config, dict)
    )


def contract_role_names() -> tuple[str, ...]:
    return tuple(contract_role_configs())


def capability_catalog() -> dict[str, dict]:
    metadata = get_contract("role_rules").get("$capabilities", {})
    return metadata if isinstance(metadata, dict) else {}


def role_risk_markers(role_name: str, config: dict) -> list[str]:
    catalog = capability_catalog()
    markers = []
    for capability, value in config.items():
        metadata = catalog.get(capability)
        if not isinstance(metadata, dict):
            continue
        risk = str(metadata.get("risk", "critical")).lower()
        if risk not in RISK_LABELS or not _is_effective_value(value):
            continue
        label = metadata.get("label", capability)
        detail = f"{role_name}: {label} — {RISK_LABELS[risk]}"
        markers.append(detail)
    return markers


def role_is_risky(role_name: str, config: dict) -> bool:
    return bool(role_risk_markers(role_name, config))


def split_user_groups(user) -> tuple[list, list]:
    role_names = set(contract_role_names())
    prefetched = getattr(user, "_prefetched_objects_cache", {}).get("groups")
    if prefetched is None:
        groups = list(user.groups.select_related("profile").order_by("name"))
    else:
        groups = sorted(prefetched, key=lambda group: group.name)
    return (
        [group for group in groups if group.name in role_names],
        [group for group in groups if group.name not in role_names],
    )


def selected_role_names_for_user(user) -> list[str]:
    role_names = set(contract_role_names())
    return sorted(user.groups.filter(name__in=role_names).values_list("name", flat=True))


def effective_capabilities_for_roles(role_names) -> dict[str, list[dict]]:
    configs = contract_role_configs()
    canonical_role_names = sorted(set(role_names))
    if not canonical_role_names:
        configs[DEFAULT_BOARD_VIEW_ROLE] = default_board_view_rules()
        canonical_role_names = [DEFAULT_BOARD_VIEW_ROLE]
    effective: dict[str, list[dict]] = {}
    for role_name in canonical_role_names:
        config = configs.get(role_name)
        if not config:
            continue
        for capability, value in config.items():
            if capability in {"display_name", "description"} or not _is_effective_value(value):
                continue
            effective.setdefault(capability, []).append({"role": role_name, "value": value})
    return effective


def access_assignment_consequences(before_roles, after_roles) -> dict:
    catalog = capability_catalog()
    before = effective_capabilities_for_roles(before_roles)
    after = effective_capabilities_for_roles(after_roles)
    added = []
    removed = []
    changed = []
    for key in sorted(set(before) | set(after)):
        label = (catalog.get(key) or {}).get("label", key)
        if key not in before:
            added.append(label)
        elif key not in after:
            removed.append(label)
        elif _canonical_capability_values(before[key]) != _canonical_capability_values(after[key]):
            changed.append(label)
    return {"added": added, "removed": removed, "changed": changed}


def user_access_overview(user) -> dict:
    role_groups, technical_groups = split_user_groups(user)
    return {
        "roles": [group.name for group in role_groups],
        "technical_groups": [group.name for group in technical_groups],
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
    }


def effective_access_for_user(user) -> dict:
    configs = contract_role_configs()
    configs[DEFAULT_BOARD_VIEW_ROLE] = default_board_view_rules()
    catalog = capability_catalog()
    role_groups, technical_groups = split_user_groups(user)
    role_names = [group.name for group in role_groups]
    capability_sources = effective_capabilities_for_roles(role_names)
    if user.is_superuser:
        for key, metadata in catalog.items():
            capability_type = (metadata or {}).get("type")
            value = True if capability_type == "flag" else "*" if capability_type == "targets" else "all"
            capability_sources.setdefault(key, []).append(
                {"role": "is_superuser", "value": value, "source_type": "is_superuser"}
            )

    capabilities = []
    for key, sources in capability_sources.items():
        meta = catalog.get(key) or {}
        capabilities.append(
            {
                "code": key,
                "label": meta.get("label", key),
                "description": meta.get("description", ""),
                "sources": [_capability_source_row(source, configs) for source in sources],
            }
        )

    roles = []
    for group in role_groups:
        config = configs[group.name]
        roles.append(
            {
                "code": group.name,
                "label": config.get("display_name", group.name),
                "description": config.get("description", ""),
                "risk_markers": role_risk_markers(group.name, config),
            }
        )
    if default_board_access_applies(user):
        default_config = configs[DEFAULT_BOARD_VIEW_ROLE]
        roles.append(
            {
                "code": DEFAULT_BOARD_VIEW_ROLE,
                "label": default_config["display_name"],
                "description": default_config["description"],
                "risk_markers": [],
                "source": "default_policy",
            }
        )

    technical = []
    for group in technical_groups:
        profile = getattr(group, "profile", None)
        technical.append(
            {
                "code": group.name,
                "label": getattr(profile, "title", "") or group.name,
                "description": getattr(profile, "description", "") or "",
                "source": "special_group",
            }
        )

    direct_permission_ids = set(user.user_permissions.values_list("id", flat=True))
    group_permission_rows = Permission.objects.filter(group__user=user).values_list(
        "id", "group__name"
    )
    groups_by_permission: dict[int, set[str]] = {}
    for permission_id, group_name in group_permission_rows:
        groups_by_permission.setdefault(permission_id, set()).add(group_name)
    permission_ids = direct_permission_ids | set(groups_by_permission)
    permissions = []
    for permission in Permission.objects.filter(id__in=permission_ids).select_related("content_type").order_by(
        "content_type__app_label", "codename"
    ):
        sources = []
        if permission.id in direct_permission_ids:
            sources.append("Назначено пользователю напрямую")
        sources.extend(f"Группа {name}" for name in sorted(groups_by_permission.get(permission.id, set())))
        permissions.append(
            {
                "code": f"{permission.content_type.app_label}.{permission.codename}",
                "label": permission.name,
                "sources": sources,
                "source": "django_permission",
            }
        )

    flags = []
    if user.is_staff:
        flags.append(
            {
                "code": "is_staff",
                "label": "Доступ к панели администрирования Django",
                "source": "is_staff",
            }
        )
    if user.is_superuser:
        flags.append(
            {
                "code": "is_superuser",
                "label": "Полный технический обход проверок доступа",
                "source": "is_superuser",
            }
        )

    return {
        "roles": roles,
        "technical_groups": technical,
        "flags": flags,
        "capabilities": capabilities,
        "django_permissions": permissions,
    }


def _is_effective_value(value) -> bool:
    return value not in (None, False, "", "none", [], {})


def _capability_source_row(source, configs):
    if source.get("source_type") == "is_superuser":
        return {
            "type": "is_superuser",
            "label": "Флаг суперпользователя",
            "code": "is_superuser",
            "value": source["value"],
        }
    role_name = source["role"]
    return {
        "type": "role",
        "label": configs[role_name].get("display_name", role_name),
        "code": role_name,
        "value": source["value"],
    }


def _canonical_capability_values(sources):
    return sorted(json.dumps(source["value"], ensure_ascii=False, sort_keys=True) for source in sources)
