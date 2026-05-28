from __future__ import annotations

from django.urls import reverse

from apps.core.right_panels import RightPanelDescriptor, register_right_panel_provider

from .models import WaitingListEntry
from .policies import can_view_waiting_list


class WaitingListRightPanelProvider:
    source_code = "waiting_list"
    object_type = "waiting_list_entry"
    supported_modes = ("view",)

    def can_open(self, user, object_id: str, mode: str = "view") -> bool:
        if mode not in self.supported_modes or not can_view_waiting_list(user):
            return False
        try:
            pk = int(str(object_id).strip())
        except (TypeError, ValueError):
            return False
        return WaitingListEntry.objects.filter(pk=pk).exists()

    def build_panel(self, user, object_id: str, mode: str = "view") -> RightPanelDescriptor:
        entry = WaitingListEntry.objects.get(pk=int(str(object_id).strip()))
        return RightPanelDescriptor(
            source_code=self.source_code,
            object_type=self.object_type,
            object_id=str(entry.pk),
            mode=mode,
            title=f"Лист ожидания {entry.pk}",
            htmx_url=reverse("waiting_list:detail", kwargs={"pk": entry.pk}),
            drawer_size="waiting_list",
            context_hint=f"waiting_list / {entry.pk}",
            metadata={"service_id": entry.service_id, "status": entry.status},
        )


def register() -> None:
    register_right_panel_provider(WaitingListRightPanelProvider(), replace=True)
