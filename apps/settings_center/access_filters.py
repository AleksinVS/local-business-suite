"""Серверные фильтры компактного списка администрирования доступа."""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Exists, OuterRef, Q

from apps.accounts.department_policy import (
    ORGANIZATION_ROOT_DEPARTMENT_NAME,
    UNASSIGNED_USER_DEPARTMENT_NAME,
)
from apps.accounts.models import ExternalIdentity
from apps.accounts.selectors import contract_role_configs
from apps.core.models import Department


ATTENTION_VALUE = "attention"


@dataclass(frozen=True)
class UserAccessFilterState:
    query: str = ""
    role: str = ""
    department_id: int | None = None
    attention: bool = False


def filter_user_queryset(queryset, params):
    """Применяет только известные фильтры и возвращает состояние для шаблона."""

    state = _parse_filter_state(params)
    role_configs = contract_role_configs()

    if state.query:
        for term in state.query.split():
            queryset = queryset.filter(
                Q(username__icontains=term)
                | Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
                | Q(email__icontains=term)
                | Q(external_identities__username__icontains=term)
                | Q(external_identities__upn__icontains=term)
                | Q(external_identities__domain__icontains=term)
                | Q(external_identities__subject_id__icontains=term)
            )

    if state.role and state.role in role_configs:
        queryset = queryset.filter(groups__name=state.role)
    elif state.role:
        queryset = queryset.none()

    if state.department_id is not None:
        department = Department.objects.filter(pk=state.department_id).first()
        if department is not None:
            queryset = queryset.filter(department_id__in=department.descendant_ids())
        else:
            queryset = queryset.none()

    if state.attention:
        membership = queryset.model.groups.through.objects.filter(user_id=OuterRef("pk"))
        queryset = queryset.annotate(
            _has_contract_role=Exists(membership.filter(group__name__in=tuple(role_configs))),
            _has_any_group=Exists(membership),
        ).filter(_attention_query())

    if state.query or state.role or state.attention:
        queryset = queryset.distinct()
    return queryset, state


def user_filter_options():
    """Возвращает малый набор известных значений без технических групп."""

    role_configs = contract_role_configs()
    return {
        "roles": [
            {
                "code": role_name,
                "label": config.get("display_name", role_name),
            }
            for role_name, config in role_configs.items()
        ],
        "departments": Department.objects.select_related("parent").order_by(
            "parent__name", "name", "id"
        ),
    }


def _parse_filter_state(params) -> UserAccessFilterState:
    raw_department_id = params.get("department", "")
    try:
        department_id = int(raw_department_id) if raw_department_id else None
    except (TypeError, ValueError):
        department_id = None
    return UserAccessFilterState(
        query=(params.get("q", "") or "").strip()[:200],
        role=(params.get("role", "") or "").strip(),
        department_id=department_id,
        attention=params.get("attention") == ATTENTION_VALUE,
    )


def _attention_query() -> Q:
    unassigned_department = Q(
        department__name=UNASSIGNED_USER_DEPARTMENT_NAME,
        department__parent__name=ORGANIZATION_ROOT_DEPARTMENT_NAME,
        department__parent__parent__isnull=True,
    )
    return (
        unassigned_department
        | Q(_has_contract_role=False)
        | Q(is_active=False, _has_any_group=True)
        | Q(external_identities__sync_status__in=(
            ExternalIdentity.SyncStatus.FAILED,
            ExternalIdentity.SyncStatus.STALE,
        ))
        | Q(is_staff=True)
        | Q(is_superuser=True)
    )
