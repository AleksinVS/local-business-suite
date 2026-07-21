from __future__ import annotations

import json
from typing import Any

from django.utils import timezone

from apps.core.source_adapters import (
    ACCESS_MODE_ADAPTER_CHECK,
    SOURCE_ORIGIN_INTERNAL,
    SourceObjectEnvelope,
    default_access_policy,
    default_provenance,
    register_source_adapter,
    stable_content_hash,
)

from .models import WorkOrder, WorkOrderStatus
from .policies import can_view


class WorkOrdersSourceAdapter:
    source_code = "workorders"
    source_origin = SOURCE_ORIGIN_INTERNAL
    source_kind = "django_model"
    domain = "workorders"
    title = "Work orders"
    adapter_version = "v1"

    def iter_changed_objects(self, watermark=None):
        queryset = (
            WorkOrder.objects.select_related("board", "department", "device", "author", "assignee")
            .prefetch_related("comments__author", "transitions__actor")
            .order_by("id")
        )
        since = (watermark or {}).get("updated_after")
        if since:
            queryset = queryset.filter(updated_at__gt=since)
        return queryset

    def get_object(self, object_id: str):
        try:
            return (
                WorkOrder.objects.select_related("board", "department", "device", "author", "assignee")
                .prefetch_related("comments__author", "transitions__actor")
                .get(pk=int(str(object_id).strip()))
            )
        except (TypeError, ValueError, WorkOrder.DoesNotExist):
            return None

    def render_envelope(self, source_object: WorkOrder, *, operation: str = "upsert") -> SourceObjectEnvelope:
        payload = self._payload(source_object)
        text = self._render_text(source_object)
        content_hash = stable_content_hash({"payload": payload, "text": text})
        return SourceObjectEnvelope(
            source_code=self.source_code,
            source_origin=self.source_origin,
            source_kind=self.source_kind,
            domain=self.domain,
            object_type="workorder",
            object_id=str(source_object.pk),
            operation=operation,
            title=f"Заявка {source_object.number}: {source_object.title}",
            text=text,
            payload=payload,
            relations=self._relations(source_object),
            content_hash=content_hash,
            source_updated_at=source_object.updated_at,
            sensitivity="internal",
            privacy_profile="pii_off",
            access_policy=default_access_policy(
                mode=ACCESS_MODE_ADAPTER_CHECK,
                policy_ref="workorders.visible",
                scope_tokens=["org:default"],
            ),
            analytics={
                "enabled": True,
                "fact_candidates": list(self.extract_analytics_facts_for_object(source_object)),
            },
            provenance=default_provenance(adapter=self.source_code, adapter_version=self.adapter_version)
            | {"source_title": self.title, "owner": "operations"},
        )

    def can_access(self, user: Any, envelope_or_object_id) -> bool:
        if getattr(user, "is_superuser", False):
            return True
        object_id = getattr(envelope_or_object_id, "object_id", envelope_or_object_id)
        source_object = self.get_object(str(object_id))
        if source_object is None:
            return False
        return can_view(user, source_object)

    def extract_analytics_facts(self, envelope: SourceObjectEnvelope):
        source_object = self.get_object(envelope.object_id)
        if source_object is None:
            return tuple((envelope.analytics or {}).get("fact_candidates", ()))
        return tuple(self.extract_analytics_facts_for_object(source_object))

    def extract_analytics_facts_for_object(self, workorder: WorkOrder):
        base_dimensions = {
            "source": "workorders",
            "workorder_id": str(workorder.pk),
            "number": workorder.number,
            "status": workorder.status,
            "priority": workorder.priority,
            "department": str(workorder.department),
            "board": workorder.board.slug if workorder.board_id else "",
            "device": workorder.device.name if workorder.device_id else "",
        }
        yield self._fact(
            workorder,
            fact_type="workorder_created",
            event_time=workorder.created_at,
            dimensions=base_dimensions,
            measures={"workorders": 1},
        )
        if workorder.status in {WorkOrderStatus.RESOLVED, WorkOrderStatus.CLOSED}:
            yield self._fact(
                workorder,
                fact_type="workorder_closed" if workorder.status == WorkOrderStatus.CLOSED else "workorder_resolved",
                event_time=workorder.closed_at or workorder.resolved_at or workorder.updated_at,
                dimensions=base_dimensions,
                measures={"workorders": 1, "rating": int(workorder.rating or 0)},
            )
        if workorder.rating:
            yield self._fact(
                workorder,
                fact_type="workorder_rated",
                event_time=workorder.updated_at,
                dimensions=base_dimensions,
                measures={"ratings": 1, "rating": int(workorder.rating)},
            )
        for transition in workorder.transitions.all():
            yield self._fact(
                workorder,
                fact_type="workorder_status_transition",
                event_time=transition.created_at,
                dimensions={
                    **base_dimensions,
                    "from_status": transition.from_status,
                    "to_status": transition.to_status,
                },
                measures={"transitions": 1},
                discriminator=f"transition:{transition.pk}",
            )
        if workorder.device_id:
            yield self._fact(
                workorder,
                fact_type="workorder_device_issue",
                event_time=workorder.created_at,
                dimensions={
                    **base_dimensions,
                    "device_id": str(workorder.device_id),
                    "device_serial": workorder.device.serial_number,
                },
                measures={"issues": 1},
            )

    def _payload(self, workorder: WorkOrder) -> dict[str, Any]:
        return {
            "business_key": f"workorder:{workorder.number}",
            "number": workorder.number,
            "status": workorder.status,
            "status_label": workorder.get_status_display(),
            "priority": workorder.priority,
            "priority_label": workorder.get_priority_display(),
            "department": str(workorder.department),
            "board": workorder.board.slug if workorder.board_id else "",
            "device": {
                "id": workorder.device_id,
                "name": workorder.device.name if workorder.device_id else "",
                "serial_number": workorder.device.serial_number if workorder.device_id else "",
            },
            "author_id": workorder.author_id,
            "assignee_id": workorder.assignee_id,
            "rating": workorder.rating,
            "closure_confirmed": workorder.closure_confirmed,
            "created_at": workorder.created_at.isoformat() if workorder.created_at else "",
            "updated_at": workorder.updated_at.isoformat() if workorder.updated_at else "",
            "resolved_at": workorder.resolved_at.isoformat() if workorder.resolved_at else "",
            "closed_at": workorder.closed_at.isoformat() if workorder.closed_at else "",
        }

    def _render_text(self, workorder: WorkOrder) -> str:
        lines = [
            f"Заявка {workorder.number}: {workorder.title}",
            f"Описание: {workorder.description}",
            f"Подразделение: {workorder.department}",
            f"Доска: {workorder.board.title if workorder.board_id else ''}",
            f"Статус: {workorder.get_status_display()}",
            f"Приоритет: {workorder.get_priority_display()}",
        ]
        if workorder.device_id:
            lines.append(f"Оборудование: {workorder.device.name} {workorder.device.serial_number}")
        if workorder.assignee_id:
            lines.append(f"Исполнитель: {workorder.assignee.get_username()}")
        if workorder.rating:
            lines.append(f"Оценка: {workorder.rating}")
        for comment in workorder.comments.all():
            lines.append(f"Комментарий: {comment.body}")
        for transition in workorder.transitions.all():
            lines.append(
                f"Переход статуса: {transition.from_status} -> {transition.to_status} "
                f"{transition.created_at:%Y-%m-%d %H:%M}"
            )
        return "\n".join(line for line in lines if line.strip())

    def _relations(self, workorder: WorkOrder):
        relations = [
            {"type": "belongs_to_board", "target": workorder.board.slug if workorder.board_id else ""},
            {"type": "belongs_to_department", "target": str(workorder.department_id)},
        ]
        if workorder.device_id:
            relations.append({"type": "mentions_device", "target": str(workorder.device_id)})
        return tuple(relations)

    def _fact(self, workorder: WorkOrder, *, fact_type: str, event_time, dimensions, measures, discriminator: str = ""):
        semantic_payload = {
            "source": self.source_code,
            "workorder_id": workorder.pk,
            "fact_type": fact_type,
            "dimensions": dimensions,
            "measures": measures,
            "discriminator": discriminator,
        }
        semantic_hash = stable_content_hash(semantic_payload)
        return {
            "fact_id": ":".join(
                item
                for item in [
                    "analytics-fact",
                    self.source_code,
                    str(workorder.pk),
                    fact_type,
                    discriminator.replace(":", "_"),
                ]
                if item
            ),
            "fact_type": fact_type,
            "event_time": (event_time or timezone.now()).isoformat(),
            "dimensions": dimensions,
            "measures": measures,
            "semantic_hash": semantic_hash,
            "scope_tokens": ["org:default"],
            "sensitivity": "internal",
        }


def register() -> None:
    register_source_adapter(WorkOrdersSourceAdapter(), replace=True)
