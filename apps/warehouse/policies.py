"""Закрытые по умолчанию складские права и области подразделений."""
from __future__ import annotations

from collections.abc import Iterable

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.department_policy import is_unassigned_user_department
from apps.core.contract_store import ContractStoreError, get_contract
from apps.core.models import Department
from apps.workorders.policies import active_role_rules, user_department_branch_ids


WAREHOUSE_VIEW_SCOPE = "warehouse_view_scope"
WAREHOUSE_OPERATE_SCOPE = "warehouse_operate_scope"
WAREHOUSE_ADJUST_SCOPE = "warehouse_adjust_scope"
WAREHOUSE_MANAGE_LOCATIONS_SCOPE = "warehouse_manage_locations_scope"
WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE = "warehouse_manage_report_profiles_scope"
WAREHOUSE_MANAGE_CATALOG = "warehouse_manage_catalog"

WAREHOUSE_SCOPED_CAPABILITIES = frozenset(
    {
        WAREHOUSE_VIEW_SCOPE,
        WAREHOUSE_OPERATE_SCOPE,
        WAREHOUSE_ADJUST_SCOPE,
        WAREHOUSE_MANAGE_LOCATIONS_SCOPE,
        WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE,
    }
)
WAREHOUSE_SCOPE_VALUES = frozenset(
    {"none", "own_department", "department_branch", "all"}
)


def _resolve_active_actor(actor):
    """Вернуть свежий снимок активного пользователя для одного решения."""

    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        return None
    return (
        get_user_model()
        .objects.filter(pk=actor.pk, is_active=True)
        .select_related("department")
        .prefetch_related("groups")
        .first()
    )


def _warehouse_rules(actor, *, rules_payload=None) -> list[dict]:
    try:
        rules = (
            rules_payload
            if isinstance(rules_payload, dict)
            else get_contract("role_rules")
        )
        return active_role_rules(actor, rules_payload=rules)
    except (ContractStoreError, ValidationError, TypeError, ValueError):
        return []


def _usable_domain_actor(actor):
    current = _resolve_active_actor(actor)
    if current is None:
        return None
    if current.is_superuser:
        return current
    if not current.department_id or is_unassigned_user_department(current.department):
        return None
    return current


def _normalized_scopes(rules: Iterable[dict], capability: str) -> set[str]:
    scopes = set()
    for rule in rules:
        value = rule.get(capability, "none") if isinstance(rule, dict) else "none"
        if value in WAREHOUSE_SCOPE_VALUES and value != "none":
            scopes.add(value)
    return scopes


def department_ids_for_warehouse_scope(
    actor,
    capability: str,
    *,
    rules_payload: dict | None = None,
) -> set[int] | None:
    """Вернуть доступные подразделения; ``None`` означает всю организацию.

    Пустое множество означает запрет. Пользователь и его группы всегда читаются
    заново, поэтому устаревший объект из запроса не сохраняет отозванное право.
    """

    if capability not in WAREHOUSE_SCOPED_CAPABILITIES:
        return set()
    current = _usable_domain_actor(actor)
    if current is None:
        return set()
    if current.is_superuser:
        return None

    scopes = _normalized_scopes(
        _warehouse_rules(current, rules_payload=rules_payload), capability
    )
    if "all" in scopes:
        return None

    department_ids: set[int] = set()
    if "own_department" in scopes:
        department_ids.add(current.department_id)
    if "department_branch" in scopes:
        department_ids.update(user_department_branch_ids(current))
    return department_ids


def warehouse_scope_allows_department(
    *,
    actor,
    capability: str,
    department: Department,
    rules_payload: dict | None = None,
) -> bool:
    """Проверить одну предметную область без выбрасывания исключения."""

    target_id = getattr(department, "pk", None)
    if not target_id or not Department.objects.filter(pk=target_id).exists():
        return False
    department_ids = department_ids_for_warehouse_scope(
        actor,
        capability,
        rules_payload=rules_payload,
    )
    return department_ids is None or target_id in department_ids


def require_warehouse_scope(
    *,
    actor,
    capability: str,
    department: Department,
) -> None:
    """Повторно проверить активного актора и складскую область ресурса.

    Сервис должен вызывать функцию после блокировки изменяемых складских строк.
    Неизвестная возможность, отсутствующий ресурс, неактивный пользователь или
    ошибка контракта приводят к ``PermissionDenied``.
    """

    if not warehouse_scope_allows_department(
        actor=actor,
        capability=capability,
        department=department,
    ):
        raise PermissionDenied("Операция недоступна в выбранном подразделении.")


def can_manage_warehouse_catalog(actor, *, rules_payload: dict | None = None) -> bool:
    """Проверить глобальное право изменения складских справочников."""

    current = _usable_domain_actor(actor)
    if current is None:
        return False
    if current.is_superuser:
        return True
    return any(
        rule.get(WAREHOUSE_MANAGE_CATALOG) is True
        for rule in _warehouse_rules(current, rules_payload=rules_payload)
    )


def require_warehouse_catalog_access(*, actor) -> None:
    """Повторно проверить глобальное право записи складского каталога."""

    if not can_manage_warehouse_catalog(actor):
        raise PermissionDenied("Управление складским каталогом запрещено.")


def can_access_warehouse(actor, *, rules_payload: dict | None = None) -> bool:
    """Показывать раздел при наличии хотя бы одного складского полномочия."""

    current = _usable_domain_actor(actor)
    if current is None:
        return False
    if current.is_superuser:
        return True
    rules = _warehouse_rules(current, rules_payload=rules_payload)
    if any(rule.get(WAREHOUSE_MANAGE_CATALOG) is True for rule in rules):
        return True
    return any(
        _normalized_scopes(rules, capability)
        for capability in WAREHOUSE_SCOPED_CAPABILITIES
    )
