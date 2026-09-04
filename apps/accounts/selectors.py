from __future__ import annotations

import json
from collections import OrderedDict

from apps.core.contract_store import get_contract
from .models import ExternalIdentity


RISK_LABELS = {"elevated": "повышенный риск", "critical": "критический риск"}
ROLE_METADATA_FIELDS = {"display_name", "description", "protected"}


def ad_identity_read_model(user):
    """Return one deterministic, provider-scoped AD presentation model.

    The model is intentionally shared by the workspace and standalone views:
    an existing row with no principal is an incomplete link, not a local user.
    """
    identities = getattr(user, "ad_identities", None)
    if identities is None:
        prefetched = getattr(user, "_prefetched_objects_cache", {}).get("external_identities")
        if prefetched is not None:
            identities = [
                identity for identity in prefetched
                if identity.provider == ExternalIdentity.Provider.ACTIVE_DIRECTORY
            ]
        else:
            identities = ExternalIdentity.objects.filter(
                user=user,
                provider=ExternalIdentity.Provider.ACTIVE_DIRECTORY,
            ).order_by("pk")
    identity = sorted(list(identities), key=lambda item: item.pk)[0] if identities else None
    if identity is None:
        return {
            "identity": None,
            "is_linked": False,
            "is_complete": False,
            "display_principal": "",
            "status_code": "not_linked",
            "status_label": "Не привязана",
            "presentation_label": "Локальная учётная запись",
        }
    values = {
        key: str(getattr(identity, key, "") or "").strip()
        for key in ("subject_id", "username", "upn", "domain", "distinguished_name")
    }
    principal = next(
        (values[key] for key in ("upn", "username", "subject_id", "domain", "distinguished_name") if values[key]),
        "",
    )
    is_complete = any(values[key] for key in ("subject_id", "username", "upn"))
    raw_status_code = str(getattr(identity, "sync_status", "") or "unknown")
    raw_status_label = identity.get_sync_status_display() if hasattr(identity, "get_sync_status_display") else raw_status_code
    display_principal = principal or "Неполная AD-связь"
    status_code = raw_status_code if is_complete else "incomplete"
    status_label = raw_status_label if is_complete else "Неполная AD-связь"
    incomplete_suffix = f" · {principal}" if principal else ""
    presentation_label = (
        f"AD: {display_principal} · {status_label}"
        if is_complete
        else f"AD: Неполная AD-связь{incomplete_suffix}"
    )
    return {
        "identity": identity,
        "is_linked": True,
        "is_complete": is_complete,
        "display_principal": display_principal,
        "status_code": status_code,
        "status_label": status_label,
        "raw_status_code": raw_status_code,
        "raw_status_label": raw_status_label,
        "presentation_label": presentation_label,
    }


def contract_role_configs(*, rules_payload=None) -> OrderedDict[str, dict]:
    rules = rules_payload if isinstance(rules_payload, dict) else get_contract("role_rules")
    return OrderedDict(
        (name, dict(config))
        for name, config in rules.items()
        if isinstance(name, str) and not name.startswith("$") and isinstance(config, dict)
    )


def contract_role_names() -> tuple[str, ...]:
    return tuple(contract_role_configs())


def default_new_user_role_name(*, rules_payload=None) -> str:
    """Вернуть настроенную роль новых пользователей или пустое значение."""

    rules = rules_payload if isinstance(rules_payload, dict) else get_contract("role_rules")
    defaults = rules.get("$defaults", {})
    role_name = defaults.get("new_user_role") if isinstance(defaults, dict) else None
    if isinstance(role_name, str) and role_name in contract_role_configs(rules_payload=rules):
        return role_name
    return ""


def capability_catalog(*, rules_payload=None) -> dict[str, dict]:
    rules = rules_payload if isinstance(rules_payload, dict) else get_contract("role_rules")
    metadata = rules.get("$capabilities", {})
    return metadata if isinstance(metadata, dict) else {}


def role_risk_markers(role_name: str, config: dict, *, catalog=None) -> list[str]:
    catalog = catalog if isinstance(catalog, dict) else capability_catalog()
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


def selected_role_names_for_user(user, *, rules_payload=None) -> list[str]:
    role_names = set(contract_role_configs(rules_payload=rules_payload))
    return sorted(user.groups.filter(name__in=role_names).values_list("name", flat=True))


def effective_capabilities_for_roles(role_names) -> dict[str, list[dict]]:
    configs = contract_role_configs()
    canonical_role_names = sorted(set(role_names))
    effective: dict[str, list[dict]] = {}
    for role_name in canonical_role_names:
        config = configs.get(role_name)
        if not config:
            continue
        for capability, value in config.items():
            if capability in ROLE_METADATA_FIELDS or not _is_effective_value(value):
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
    from apps.memory.policies import MEMORY_REVIEW_GROUP_CAPABILITIES

    memory_names = set(MEMORY_REVIEW_GROUP_CAPABILITIES)
    return {
        "roles": [group.name for group in role_groups],
        "technical_groups": [group.name for group in technical_groups if group.name not in memory_names],
        "memory_groups": [group.name for group in technical_groups if group.name in memory_names],
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
    }


def effective_access_for_user(user) -> dict:
    configs = contract_role_configs()
    catalog = capability_catalog()
    role_groups, technical_groups = split_user_groups(user)
    memory_group_names = set()
    try:
        from apps.memory.policies import MEMORY_REVIEW_GROUP_CAPABILITIES

        memory_group_names = set(MEMORY_REVIEW_GROUP_CAPABILITIES)
    except ImportError:
        # Keep this selector usable during early app loading.  Memory groups
        # are still separated whenever the memory policy module is available.
        pass
    role_names = [group.name for group in role_groups]
    is_active = bool(getattr(user, "is_active", False))
    # Enforcement short-circuits to the superuser reserve.  Do not mix the
    # legacy roleless fallback into that explanation: assigned roles remain
    # visible as facts below, while effective grants have one truthful source.
    capability_sources = (
        effective_capabilities_for_roles(role_names)
        if is_active and not user.is_superuser
        else {}
    )
    if is_active and user.is_superuser:
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
                "effective": is_active,
            }
        )
    technical = []
    memory = []
    for group in technical_groups:
        profile = getattr(group, "profile", None)
        row = {
            "code": group.name,
            "label": getattr(profile, "title", "") or group.name,
            "description": getattr(profile, "description", "") or "",
            "source": "technical_group",
            "effective": is_active,
        }
        (memory if group.name in memory_group_names else technical).append(row)

    flags = []
    if is_active and user.is_staff:
        flags.append(
            {
                "code": "is_staff",
                "label": "Доступ к панели администрирования Django",
                "source": "is_staff",
            }
        )
    if is_active and user.is_superuser:
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
        "memory_groups": memory,
        "flags": flags,
        "capabilities": capabilities,
        "superuser_reserve": {
            "assigned": bool(user.is_superuser),
            "effective": bool(is_active and user.is_superuser),
            "source": "superuser_reserve",
        },
        # ACL and workflow are object-scoped restrictions, not grant sources.
        # Keep their presence explicit without serializing complete ACLs.
        "constraints": [
            {
                "type": "acl",
                "source": "resource_acl",
                "label": "ACL конкретного ресурса сужает доступ",
                "object_scoped": True,
                "effect": "narrows_role_scope",
            },
            {
                "type": "workflow",
                "source": "workflow",
                "label": "Статус и переходы процесса сужают доступ",
                "object_scoped": True,
                "effect": "narrows_transitions",
            },
        ],
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
