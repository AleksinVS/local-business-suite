"""Access-administration providers for the shared autocomplete transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.core.autocomplete import AutocompleteOption, register_autocomplete_provider
from apps.workorders.policies import can_manage_roles
from apps.workorders.selectors import resolve_active_actor

from .department_policy import available_user_departments
from .services import assignable_role_names_for_actor


@dataclass(frozen=True)
class UserDepartmentAutocompleteProvider:
    code: str = "accounts.department"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ()
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return bool(actor and actor.is_superuser)

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        departments = available_user_departments()
        if query:
            departments = departments.filter(name__icontains=query)
        return [
            AutocompleteOption(
                value=department.pk,
                label=getattr(department, "indented_name", department.name),
                secondary=getattr(department, "full_name", ""),
            )
            for department in departments[:limit]
        ]


@dataclass(frozen=True)
class RolePrincipalAutocompleteProvider:
    code: str = "accounts.role_principal"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("role",)
    result_limit: int = 20

    def can_use(self, user) -> bool:
        actor = resolve_active_actor(user, force_refresh=True)
        return bool(actor and can_manage_roles(actor))

    def search(self, *, user, query: str, context: Mapping[str, str], limit: int):
        actor = resolve_active_actor(user, force_refresh=True)
        role_name = (context.get("role") or "").strip()
        if actor is None or not role_name:
            return []
        candidates = get_user_model().objects.filter(is_active=True).order_by("username", "pk")
        if query:
            candidates = candidates.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
            )
        options = []
        # Authority is target-dependent. Do not return a principal merely because
        # the actor can open the access workspace.
        for target in candidates[: max(limit * 5, 50)]:
            try:
                assignable = assignable_role_names_for_actor(actor=actor, target_user=target)
            except PermissionDenied:
                continue
            if role_name not in assignable:
                continue
            options.append(
                AutocompleteOption(
                    value=target.pk,
                    label=target.get_full_name() or target.username,
                    secondary=target.username,
                )
            )
            if len(options) >= limit:
                break
        return options


def register() -> None:
    register_autocomplete_provider(UserDepartmentAutocompleteProvider(), replace=True)
    register_autocomplete_provider(RolePrincipalAutocompleteProvider(), replace=True)
