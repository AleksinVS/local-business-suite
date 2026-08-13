"""Read model for the unified access administration workspace.

The workspace deliberately composes data from prefetched users, the role
contract and domain-owned models.  It does not call ``effective_access_for_user``
for each table row: section names are derived from the already loaded role
groups and the capability catalog.
"""
from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.accounts.selectors import capability_catalog, contract_role_configs, role_risk_markers, split_user_groups
from apps.accounts.access_contracts import CAPABILITY_GROUP_LABELS, capability_group_code
from apps.core.models import Department
from apps.memory.policies import MEMORY_REVIEW_GROUP_CAPABILITIES, MEMORY_REVIEW_GROUP_PROFILES
from apps.workorders.models import Board


TABS = (
    ("users", "Пользователи"),
    ("roles", "Роли"),
    ("boards", "Доски"),
    ("site-sections", "Разделы сайта"),
    ("technical-groups", "Технические группы"),
    ("memory-groups", "Группы памяти"),
)
TAB_CODES = frozenset(code for code, _label in TABS)
FIELD_CODES = {
    "users": frozenset({"profile", "status", "department", "ad", "roles", "site-sections", "technical-groups", "memory-groups"}),
    "roles": frozenset({"definition", "description", "users"}),
    "boards": frozenset({"groups"}),
    "site-sections": frozenset({"roles"}),
    "technical-groups": frozenset({"description", "users"}),
    "memory-groups": frozenset({"description", "users"}),
}
FIELD_LABELS = {
    "profile": "Профиль пользователя",
    "status": "Статус учетной записи",
    "department": "Подразделение",
    "ad": "Связь с Active Directory",
    "roles": "Роли доступа",
    "site-sections": "Разделы сайта",
    "technical-groups": "Технические группы",
    "memory-groups": "Группы памяти",
    "definition": "Определение роли",
    "description": "Описание роли",
    "users": "Пользователи",
    "groups": "Группы доступа к доске",
}
KIND_LABELS = {
    "user": "Пользователь",
    "role": "Роль",
    "board": "Доска",
    "site-section": "Раздел сайта",
    "technical-group": "Техническая группа",
    "memory-group": "Группа памяти",
}
SECTION_LABELS = dict(CAPABILITY_GROUP_LABELS)


def workspace_context(*, query_params=None):
    """Return the complete, query-efficient read model used by the shell."""
    query_params = query_params or {}
    from .access_filters import ATTENTION_VALUE, filter_user_queryset

    all_users = list(_user_queryset())
    filter_keys = ("q", "role", "department", "attention")
    has_user_filter = any(query_params.get(key) for key in filter_keys)
    if has_user_filter:
        user_queryset, filter_state = filter_user_queryset(_user_queryset(), query_params)
        users = list(user_queryset)
    else:
        _, filter_state = filter_user_queryset(_user_queryset().none(), query_params)
        users = all_users
    department_paths = _department_path_cache()
    filter_options = _department_filter_options(department_paths)
    role_configs = contract_role_configs()
    catalog = capability_catalog()
    rows = build_user_rows(users, role_configs=role_configs, catalog=catalog, department_paths=department_paths)
    group_rows = _group_rows(all_users, role_configs)
    role_rows = _role_rows(all_users, role_configs)
    board_rows = _board_rows(role_configs)
    section_rows = _section_rows(users, role_configs, catalog)

    tab = query_params.get("view", "users")
    if tab not in TAB_CODES:
        tab = "users"
    selected = _selected_record(tab, query_params.get("object"), {
        "users": rows,
        "roles": role_rows,
        "boards": board_rows,
        "site-sections": section_rows,
        "technical-groups": group_rows["technical"],
        "memory-groups": group_rows["memory"],
    })
    field = query_params.get("field", "")
    if field not in FIELD_CODES.get(tab, ()):
        field = "profile" if tab == "users" else "definition" if tab == "roles" else ""
    return {
        "tabs": [{"code": code, "label": label, "active": code == tab} for code, label in TABS],
        "active_tab": tab,
        "users": rows,
        "roles": role_rows,
        "boards": board_rows,
        "site_sections": section_rows,
        "technical_groups": group_rows["technical"],
        "memory_groups": group_rows["memory"],
        "selected": selected,
        "selected_field": field if selected else "",
        "selected_field_label": FIELD_LABELS.get(field, field),
        "selected_kind_label": KIND_LABELS.get(selected.get("kind"), selected.get("kind", "")) if selected else "",
        "selected_panel": "field" if selected and query_params.get("panel") == "field" else ("inspector" if selected else ""),
        "standalone_target": _standalone_target(selected),
        "access_filter_state": filter_state,
        "attention_value": ATTENTION_VALUE,
        "role_filter_options": _role_filter_options(role_configs),
        "department_filter_options": filter_options,
        "filter_query": urlencode({key: query_params.get(key) for key in ("q", "role", "department", "attention") if query_params.get(key)}),
    }


def _user_queryset():
    return (
        get_user_model()
        .objects.select_related("department", "department__parent")
        .prefetch_related("groups__profile", "external_identities")
        .order_by("username", "pk")
    )


def _department_path_cache():
    """Build every department path in memory with one query, including deep trees."""
    nodes = {
        row["id"]: {"name": row["name"], "parent_id": row["parent_id"]}
        for row in Department.objects.values("id", "name", "parent_id")
    }
    paths = {}
    for node_id in nodes:
        trail = []
        current = node_id
        seen = set()
        while current in nodes and current not in seen:
            seen.add(current)
            node = nodes[current]
            trail.append(node["name"])
            current = node["parent_id"]
        paths[node_id] = " / ".join(reversed(trail))
    return paths


def _department_filter_options(paths):
    return [{"pk": node_id, "full_name": path} for node_id, path in sorted(paths.items(), key=lambda item: item[1].casefold())]


def _role_filter_options(role_configs):
    return [{"code": name, "label": config.get("display_name", name)} for name, config in role_configs.items()]


def build_user_rows(users, *, role_configs=None, catalog=None, department_paths=None):
    role_configs = role_configs or contract_role_configs()
    catalog = catalog or capability_catalog()
    memory_names = set(MEMORY_REVIEW_GROUP_CAPABILITIES)
    section_by_role = _sections_by_role(role_configs, catalog)
    rows = []
    for user in users:
        role_groups, technical_groups = split_user_groups(user)
        role_codes = [group.name for group in role_groups]
        role_labels = [
            getattr(getattr(group, "profile", None), "title", "") or role_configs.get(group.name, {}).get("display_name", group.name)
            for group in role_groups
        ]
        technical = [
            {
                "code": group.name,
                "label": getattr(getattr(group, "profile", None), "title", "") or group.name,
            }
            for group in technical_groups
            if group.name not in memory_names
        ]
        memory = [
            {
                "code": group.name,
                "label": getattr(getattr(group, "profile", None), "title", "") or group.name,
            }
            for group in technical_groups
            if group.name in memory_names
        ]
        identities = list(user.external_identities.all())
        identity = identities[0] if identities else None
        ad_label = ""
        if identity:
            ad_label = identity.upn or identity.username or identity.subject_id or identity.domain
        sections = set()
        for role_code in role_codes:
            sections.update(section_by_role.get(role_code, ()))
        if not role_codes and user.is_active:
            sections.add(SECTION_LABELS["workorders"])
        if user.is_superuser:
            sections.update(_section_labels(catalog))
        rows.append(
            {
                "kind": "user",
                "id": user.pk,
                "object": str(user.pk),
                "name": user.get_full_name() or user.username,
                "username": user.username,
                "email": user.email,
                "ad": ad_label or "Не привязан",
                "ad_identity": identity,
                "department": user.department.name if user.department else "Без подразделения",
                "department_full": (department_paths or {}).get(user.department_id, "Без подразделения"),
                "role_sources": ([{"label": "Базовый просмотр канбана", "code": "default_board_viewer", "read_only": True}] if not role_codes and user.is_active else []),
                "status": {
                    "icon": "●" if user.is_active else "○",
                    "label": "Активен" if user.is_active else "Отключён",
                    "class": "is-active" if user.is_active else "is-inactive",
                },
                "roles": role_labels or (["Базовый просмотр канбана"] if not role_codes and user.is_active else []),
                "roles_text": ", ".join(role_labels or (["Базовый просмотр канбана"] if not role_codes and user.is_active else [])),
                "role_codes": role_codes,
                "site_sections": sorted(sections),
                "site_sections_text": ", ".join(sorted(sections)),
                "technical_groups": technical,
                "technical_groups_text": ", ".join(group["label"] for group in technical),
                "memory_groups": memory,
                "memory_groups_text": ", ".join(group["label"] for group in memory),
                "user": user,
            }
        )
    return rows


def _sections_by_role(role_configs, catalog):
    result = defaultdict(set)
    for role_code, config in role_configs.items():
        for code, value in config.items():
            if code in {"display_name", "description"} or value in (None, False, "", "none", [], {}):
                continue
            metadata = catalog.get(code) or {}
            section = capability_group_code(code, metadata)
            result[role_code].add(SECTION_LABELS.get(section, section))
    return result


def _section_labels(catalog):
    return {SECTION_LABELS.get(capability_group_code(code, metadata), "Прочие права") for code, metadata in catalog.items() if isinstance(metadata, dict)}


def _role_rows(users, role_configs):
    members = defaultdict(list)
    for user in users:
        role_groups, _technical_groups = split_user_groups(user)
        for group in role_groups:
            members[group.name].append(user)
    rows = []
    for code, config in role_configs.items():
        row = {
            "kind": "role",
            "id": code,
            "object": code,
            "code": code,
            "name": config.get("display_name", code),
            "label": config.get("display_name", code),
            "description": config.get("description", ""),
            "users": [user.get_full_name() or user.username for user in members.get(code, [])],
            "users_text": ", ".join(user.get_full_name() or user.username for user in members.get(code, [])),
            "user_objects": members.get(code, []),
            "member_count": len(members.get(code, [])),
            "risk": {},
        }
        risk_markers = role_risk_markers(code, config)
        row["risk"] = {"markers": risk_markers}
        rows.append(row)
    return rows


def _board_rows(role_configs):
    rows = []
    for board in Board.objects.prefetch_related("allowed_groups__profile").order_by("title", "pk"):
        groups = list(board.allowed_groups.all())
        rows.append(
            {
                "kind": "board",
                "id": board.pk,
                "object": str(board.pk),
                "name": board.title,
                "title": board.title,
                "slug": board.slug,
                "groups": [getattr(getattr(group, "profile", None), "title", "") or group.name for group in groups],
                "groups_text": ", ".join(getattr(getattr(group, "profile", None), "title", "") or group.name for group in groups),
                "group_codes": [group.name for group in groups],
                "board": board,
            }
        )
    return rows


def _section_rows(users, role_configs, catalog):
    sections = defaultdict(set)
    for code, config in role_configs.items():
        for capability, value in config.items():
            if capability in {"display_name", "description"} or value in (None, False, "", "none", [], {}):
                continue
            metadata = catalog.get(capability) or {}
            section = capability_group_code(capability, metadata)
            sections[section].add(code)
    return [
        {
            "kind": "site-section",
            "id": code,
            "object": code,
            "code": code,
            "name": SECTION_LABELS.get(code, code),
            "description": "Раздел сайта, собранный из возможностей контракта ролей.",
            "roles": sorted(roles),
            "roles_text": ", ".join(sorted(roles)),
            "capability_count": sum(1 for capability, metadata in catalog.items() if isinstance(metadata, dict) and capability_group_code(capability, metadata) == code),
        }
        for code, roles in sorted(sections.items(), key=lambda item: SECTION_LABELS.get(item[0], item[0]))
    ]


def _group_rows(users, role_configs):
    role_names = set(role_configs)
    memory_names = set(MEMORY_REVIEW_GROUP_CAPABILITIES)
    members = defaultdict(list)
    for user in users:
        for group in user.groups.all():
            members[group.name].append(user)
    groups = {
        group.name: group
        for group in Group.objects.exclude(name__in=role_names).exclude(name__in=memory_names).prefetch_related("profile")
    }
    technical = []
    for code, group in sorted(groups.items()):
        profile = getattr(group, "profile", None)
        technical.append(
            {
                "kind": "technical-group",
                "id": group.pk,
                "object": code,
                "code": code,
                "name": getattr(profile, "title", "") or code,
                "description": getattr(profile, "description", "") or "Техническая группа без описания.",
                "users": [user.get_full_name() or user.username for user in members.get(code, [])],
                "users_text": ", ".join(user.get_full_name() or user.username for user in members.get(code, [])),
                "group": group,
            }
        )
    memory = []
    for code, profile_data in sorted(MEMORY_REVIEW_GROUP_PROFILES.items()):
        memory.append(
            {
                "kind": "memory-group",
                "id": code,
                "object": code,
                "code": code,
                "name": profile_data[0],
                "description": profile_data[1],
                "users": [user.get_full_name() or user.username for user in members.get(code, [])],
                "users_text": ", ".join(user.get_full_name() or user.username for user in members.get(code, [])),
            }
        )
    return {"technical": technical, "memory": memory}


def _selected_record(tab, object_id, records):
    if not object_id:
        return None
    return next((row for row in records.get(tab, ()) if str(row.get("object")) == str(object_id)), None)


def _standalone_target(selected):
    if not selected:
        return ""
    kind = selected.get("kind")
    if kind == "user":
        return f"/settings/users/{selected['id']}/edit/"
    if kind == "role":
        return f"/settings/access/roles/{selected['code']}/"
    if kind == "board":
        return f"/settings/boards/{selected['id']}/access/"
    if kind == "memory-group":
        return "/memory/review/"
    return ""
