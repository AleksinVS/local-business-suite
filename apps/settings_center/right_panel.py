"""Server-owned access editor handoff providers.

Only the two existing human editors can be opened.  Callers cannot supply a
URL, source, object type, or arbitrary object; the provider resolves those
values from the contract role catalog or the user table.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from urllib.parse import urlencode

from apps.accounts.selectors import contract_role_configs
from apps.core.right_panels import RightPanelDescriptor, register_right_panel_provider
from apps.workorders.policies import can_manage_roles
from apps.workorders.selectors import resolve_active_actor


class _AccessEditorProvider:
    supported_modes = ("edit",)

    def __init__(self, object_type: str):
        self.source_code = "settings_center"
        self.object_type = object_type

    def can_open(self, user, object_id: str, mode: str = "edit") -> bool:
        fresh_actor = resolve_active_actor(user, force_refresh=True)
        if mode not in self.supported_modes or fresh_actor is None or not can_manage_roles(fresh_actor):
            return False
        if self.object_type == "role":
            return object_id in contract_role_configs()
        try:
            target_id = int(str(object_id).strip())
        except (TypeError, ValueError):
            return False
        return get_user_model().objects.filter(pk=target_id).exists()

    def build_panel(self, user, object_id: str, mode: str = "edit") -> RightPanelDescriptor:
        fresh_actor = resolve_active_actor(user, force_refresh=True)
        if mode not in self.supported_modes or fresh_actor is None or not can_manage_roles(fresh_actor):
            raise PermissionDenied("Редактор доступа недоступен для текущего администратора.")
        if self.object_type == "role":
            try:
                role = contract_role_configs()[object_id]
            except KeyError as exc:
                raise ValidationError("Контрактная роль больше не существует.") from exc
            label = role.get("display_name", object_id)
            return RightPanelDescriptor(
                source_code=self.source_code,
                object_type=self.object_type,
                object_id=object_id,
                mode=mode,
                title=f"Редактор роли: {label}",
                htmx_url=f"{reverse('settings_center:access_workspace')}?{urlencode({'view': 'roles', 'object': object_id, 'field': 'definition', 'panel': 'inspector'})}",
                drawer_size="large",
                context_hint=f"settings_center / role / {object_id}",
                metadata={"target_type": "role"},
            )
        try:
            target = get_user_model().objects.get(pk=int(str(object_id).strip()))
        except (TypeError, ValueError, get_user_model().DoesNotExist) as exc:
            raise PermissionDenied("Пользователь больше не существует.") from exc
        return RightPanelDescriptor(
            source_code=self.source_code,
            object_type=self.object_type,
            object_id=str(target.pk),
            mode=mode,
            title=f"Редактор доступа: пользователь #{target.pk}",
            htmx_url=f"{reverse('settings_center:access_workspace')}?{urlencode({'view': 'users', 'object': target.pk, 'field': 'roles', 'panel': 'inspector'})}",
            drawer_size="large",
            context_hint=f"settings_center / user / {target.pk}",
            metadata={"target_type": "user"},
        )


def register() -> None:
    register_right_panel_provider(_AccessEditorProvider("user"), replace=True)
    register_right_panel_provider(_AccessEditorProvider("role"), replace=True)
