from __future__ import annotations

from django.urls import reverse

from apps.core.right_panels import RightPanelDescriptor, register_right_panel_provider

from .selectors import visible_workorders_queryset


class WorkOrderRightPanelProvider:
    source_code = "workorders"
    object_type = "workorder"
    supported_modes = ("view",)

    def can_open(self, user, object_id: str, mode: str = "view") -> bool:
        if mode not in self.supported_modes:
            return False
        try:
            pk = int(str(object_id).strip())
        except (TypeError, ValueError):
            return False
        return visible_workorders_queryset(user).filter(pk=pk).exists()

    def build_panel(self, user, object_id: str, mode: str = "view") -> RightPanelDescriptor:
        workorder = visible_workorders_queryset(user).get(pk=int(str(object_id).strip()))
        return RightPanelDescriptor(
            source_code=self.source_code,
            object_type=self.object_type,
            object_id=str(workorder.pk),
            mode=mode,
            title=f"Заявка {workorder.number}",
            htmx_url=reverse("workorders:detail", kwargs={"pk": workorder.pk}),
            drawer_size="large",
            context_hint=f"workorders / {workorder.number}",
            metadata={"number": workorder.number},
        )


def register() -> None:
    register_right_panel_provider(WorkOrderRightPanelProvider(), replace=True)
