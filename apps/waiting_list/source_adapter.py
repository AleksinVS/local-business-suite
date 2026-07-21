from __future__ import annotations

from typing import Any

from django.conf import settings
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
from apps.memory.deidentification import pseudonymize_value

from .models import WaitingListEntry, WaitingListStatus
from .policies import can_view_waiting_list


class WaitingListSourceAdapter:
    source_code = "waiting_list"
    source_origin = SOURCE_ORIGIN_INTERNAL
    source_kind = "django_model"
    domain = "waiting_list"
    title = "Waiting list"
    adapter_version = "v1"

    def iter_changed_objects(self, watermark=None):
        queryset = WaitingListEntry.objects.select_related("author").prefetch_related("audit_logs__actor").order_by("id")
        since = (watermark or {}).get("updated_after")
        if since:
            queryset = queryset.filter(updated_at__gt=since)
        return queryset

    def get_object(self, object_id: str):
        try:
            return (
                WaitingListEntry.objects.select_related("author")
                .prefetch_related("audit_logs__actor")
                .get(pk=int(str(object_id).strip()))
            )
        except (TypeError, ValueError, WaitingListEntry.DoesNotExist):
            return None

    def render_envelope(self, source_object: WaitingListEntry, *, operation: str = "upsert") -> SourceObjectEnvelope:
        payload = self._payload(source_object)
        text = self._render_text(source_object)
        content_hash = stable_content_hash({"payload": payload, "text": text})
        return SourceObjectEnvelope(
            source_code=self.source_code,
            source_origin=self.source_origin,
            source_kind=self.source_kind,
            domain=self.domain,
            object_type="waiting_list_entry",
            object_id=str(source_object.pk),
            operation=operation,
            title=f"Лист ожидания {source_object.pk}: {source_object.get_service_id_display()}",
            text=text,
            payload=payload,
            relations=(),
            content_hash=content_hash,
            source_updated_at=source_object.updated_at,
            sensitivity="internal",
            privacy_profile="pii_off",
            access_policy=default_access_policy(
                mode=ACCESS_MODE_ADAPTER_CHECK,
                policy_ref="waiting_list.visible",
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
        return bool(getattr(user, "is_superuser", False) or can_view_waiting_list(user))

    def extract_analytics_facts(self, envelope: SourceObjectEnvelope):
        source_object = self.get_object(envelope.object_id)
        if source_object is None:
            return tuple((envelope.analytics or {}).get("fact_candidates", ()))
        return tuple(self.extract_analytics_facts_for_object(source_object))

    def extract_analytics_facts_for_object(self, entry: WaitingListEntry):
        base_dimensions = {
            "source": self.source_code,
            "entry_id": str(entry.pk),
            "service_id": entry.service_id,
            "service": entry.get_service_id_display(),
            "status": entry.status,
            "priority_cito": bool(entry.priority_cito),
        }
        yield self._fact(
            entry,
            fact_type="waiting_list_entry_created",
            event_time=entry.created_at,
            dimensions=base_dimensions,
            measures={"entries": 1},
        )
        if entry.status == WaitingListStatus.SCHEDULED:
            yield self._fact(
                entry,
                fact_type="waiting_list_entry_scheduled",
                event_time=entry.updated_at,
                dimensions=base_dimensions,
                measures={"entries": 1, "waiting_days": self._waiting_days(entry)},
            )
        if entry.status == WaitingListStatus.CONFIRMED:
            yield self._fact(
                entry,
                fact_type="waiting_list_entry_confirmed",
                event_time=entry.updated_at,
                dimensions=base_dimensions,
                measures={"entries": 1, "waiting_days": self._waiting_days(entry)},
            )
        if entry.status == WaitingListStatus.CANCELLED:
            yield self._fact(
                entry,
                fact_type="waiting_list_entry_cancelled",
                event_time=entry.updated_at,
                dimensions=base_dimensions,
                measures={"entries": 1},
            )
        if entry.priority_cito:
            yield self._fact(
                entry,
                fact_type="waiting_list_entry_cito",
                event_time=entry.created_at,
                dimensions=base_dimensions,
                measures={"cito_entries": 1},
            )
        yield self._fact(
            entry,
            fact_type="waiting_list_waiting_time",
            event_time=entry.updated_at,
            dimensions=base_dimensions,
            measures={"waiting_days": self._waiting_days(entry)},
        )

    def _payload(self, entry: WaitingListEntry) -> dict[str, Any]:
        return {
            "business_key": f"waiting-list:{entry.pk}",
            "external_id": str(entry.external_id),
            "service_id": entry.service_id,
            "service": entry.get_service_id_display(),
            "status": entry.status,
            "status_label": entry.get_status_display(),
            "priority_cito": entry.priority_cito,
            "date_tag": entry.date_tag.isoformat() if entry.date_tag else "",
            "date_end": entry.date_end.isoformat() if entry.date_end else "",
            "author_id": entry.author_id,
            "created_at": entry.created_at.isoformat() if entry.created_at else "",
            "updated_at": entry.updated_at.isoformat() if entry.updated_at else "",
        }

    def _render_text(self, entry: WaitingListEntry) -> str:
        lines = [
            f"Лист ожидания {entry.pk}",
            f"Услуга: {entry.get_service_id_display()}",
            f"Статус: {entry.get_status_display()}",
            f"CITO: {'да' if entry.priority_cito else 'нет'}",
            f"Целевая дата: {entry.date_tag.isoformat() if entry.date_tag else ''}",
            f"Крайняя дата: {entry.date_end.isoformat() if entry.date_end else ''}",
            f"Комментарий: {entry.comment}",
            f"Пациент: {self._patient_pseudonym(entry)}",
        ]
        for audit_log in entry.audit_logs.all():
            lines.append(f"Журнал: {audit_log.action} {audit_log.created_at:%Y-%m-%d %H:%M}")
        return "\n".join(line for line in lines if line.strip())

    def _patient_pseudonym(self, entry: WaitingListEntry) -> str:
        value = f"{entry.external_id}:{entry.pk}"
        return pseudonymize_value(value, secret_key=settings.SECRET_KEY, entity_type="PATIENT")

    def _waiting_days(self, entry: WaitingListEntry) -> int:
        if not entry.date_tag:
            return 0
        return max((entry.date_tag - entry.created_at.date()).days, 0)

    def _fact(self, entry: WaitingListEntry, *, fact_type: str, event_time, dimensions, measures):
        semantic_payload = {
            "source": self.source_code,
            "entry_id": entry.pk,
            "fact_type": fact_type,
            "dimensions": dimensions,
            "measures": measures,
        }
        semantic_hash = stable_content_hash(semantic_payload)
        return {
            "fact_id": f"analytics-fact:{self.source_code}:{entry.pk}:{fact_type}",
            "fact_type": fact_type,
            "event_time": (event_time or timezone.now()).isoformat(),
            "dimensions": dimensions,
            "measures": measures,
            "semantic_hash": semantic_hash,
            "scope_tokens": ["org:default"],
            "sensitivity": "internal",
        }


def register() -> None:
    register_source_adapter(WaitingListSourceAdapter(), replace=True)
