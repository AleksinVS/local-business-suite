"""Server-owned right-panel descriptors for warehouse documents."""

from __future__ import annotations

from django.urls import reverse

from apps.core.right_panels import RightPanelDescriptor, register_right_panel_provider

from .models import StockDocument
from .policies import WAREHOUSE_OPERATE_SCOPE, warehouse_scope_allows_department
from .selectors import visible_stock_documents_queryset
from .policies import department_ids_for_warehouse_scope


class WarehouseDocumentRightPanelProvider:
    source_code = "warehouse"
    object_type = "document"
    supported_modes = ("view", "create", "edit")

    def can_open(self, user, object_id: str, mode: str = "view") -> bool:
        if mode not in self.supported_modes:
            return False
        if mode == "create":
            return department_ids_for_warehouse_scope(user, WAREHOUSE_OPERATE_SCOPE) != set()
        try:
            document = visible_stock_documents_queryset(user).select_related("department").get(pk=int(str(object_id)))
        except (TypeError, ValueError, StockDocument.DoesNotExist):
            return False
        if mode == "edit":
            return document.status == StockDocument.Status.DRAFT and warehouse_scope_allows_department(
                actor=user, capability=WAREHOUSE_OPERATE_SCOPE, department=document.department
            )
        return True

    def build_panel(self, user, object_id: str, mode: str = "view") -> RightPanelDescriptor:
        if mode == "create":
            return RightPanelDescriptor(
                source_code=self.source_code,
                object_type=self.object_type,
                object_id="new",
                mode=mode,
                title="Новый складской документ",
                htmx_url=reverse("warehouse:document_new_panel"),
                drawer_size="workspace",
                context_hint="warehouse / create",
            )
        document = visible_stock_documents_queryset(user).get(pk=int(str(object_id)))
        if mode == "edit":
            url = reverse("warehouse:document_edit_panel", kwargs={"pk": document.pk})
            title = f"Редактирование документа №{document.number or '—'}"
        else:
            url = reverse("warehouse:document_detail_panel", kwargs={"pk": document.pk})
            title = f"Документ №{document.number or '—'}"
        return RightPanelDescriptor(
            source_code=self.source_code,
            object_type=self.object_type,
            object_id=str(document.pk),
            mode=mode,
            title=title,
            htmx_url=url,
            drawer_size="workspace",
            context_hint=f"warehouse / {document.operation_date}",
            metadata={"document_type": document.document_type, "status": document.status},
        )


def register() -> None:
    register_right_panel_provider(WarehouseDocumentRightPanelProvider(), replace=True)
