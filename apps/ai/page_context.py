from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.workorders.policies import (
    can_comment,
    can_confirm_closure,
    can_rate,
    can_transition,
)
from apps.workorders.selectors import visible_workorders_queryset
from apps.workorders.models import WorkOrder, WorkOrderStatus

from .models import AIWindowContextSnapshot, ChatMessage


PAGE_CONTEXT_SCHEMA_VERSION = "1"
PAGE_CONTEXT_MAX_BYTES = 16 * 1024
PAGE_CONTEXT_TTL_HOURS = 24
ALLOWED_MODULES = {
    "workorders",
    "inventory",
    "waiting_list",
    "memory",
    "analytics",
    "ai",
    "core",
    "settings_center",
    "admin",
    "",
}
ALLOWED_TOP_LEVEL_KEYS = {"schema_version", "window_id", "context_version", "page", "selection", "filters", "ui_state", "capabilities"}
ALLOWED_PAGE_KEYS = {"path", "title", "module", "view"}
ALLOWED_SELECTION_KEYS = {"object_type", "object_id", "source_code", "display"}
ALLOWED_UI_STATE_KEYS = {"right_drawer", "focused_region"}
SAFE_TEXT_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class ContextUpdateResult:
    snapshot: AIWindowContextSnapshot
    created: bool


def sanitize_page_context_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise ValidationError("Page context envelope must be a JSON object.")
    encoded = json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) > PAGE_CONTEXT_MAX_BYTES:
        raise ValidationError("Page context envelope is too large.")

    clean: dict[str, Any] = {
        "schema_version": str(envelope.get("schema_version") or PAGE_CONTEXT_SCHEMA_VERSION),
        "window_id": _safe_string(envelope.get("window_id"), max_len=128),
        "page": _sanitize_mapping(envelope.get("page"), ALLOWED_PAGE_KEYS, max_value_len=200),
        "selection": _sanitize_mapping(envelope.get("selection"), ALLOWED_SELECTION_KEYS, max_value_len=240),
        "filters": _sanitize_mapping(envelope.get("filters"), None, max_value_len=120),
        "ui_state": _sanitize_mapping(envelope.get("ui_state"), ALLOWED_UI_STATE_KEYS, max_value_len=80),
        "capabilities": {},
    }
    if clean["schema_version"] != PAGE_CONTEXT_SCHEMA_VERSION:
        raise ValidationError("Unsupported page context schema_version.")
    if not clean["window_id"]:
        raise ValidationError("window_id is required.")
    module = _safe_string(clean["page"].get("module"), max_len=64).lower()
    if module not in ALLOWED_MODULES:
        raise ValidationError("Unknown page context module.")
    clean["page"]["module"] = module
    if clean["selection"]:
        clean["selection"]["object_id"] = _safe_string(clean["selection"].get("object_id"), max_len=80)
        clean["selection"]["source_code"] = _safe_string(clean["selection"].get("source_code"), max_len=80)
        clean["selection"]["object_type"] = _safe_string(clean["selection"].get("object_type"), max_len=80)
        clean["selection"]["display"] = _safe_string(clean["selection"].get("display"), max_len=160)
    return clean


def resolve_page_context(user, envelope: dict[str, Any]) -> dict[str, Any]:
    page = envelope.get("page") or {}
    selection = envelope.get("selection") or {}
    summary = {
        "status": "ok",
        "page": {
            "module": page.get("module", ""),
            "view": page.get("view", ""),
            "path": page.get("path", ""),
            "title": page.get("title", ""),
        },
        "selection": {},
        "filters": envelope.get("filters") or {},
        "ui_state": envelope.get("ui_state") or {},
        "capabilities": {},
        "context_hint": build_context_hint(envelope),
    }
    if not selection:
        return summary

    source_code = selection.get("source_code", "")
    object_type = selection.get("object_type", "")
    object_id = selection.get("object_id", "")
    if source_code == "workorders" and object_type == "workorder" and object_id:
        try:
            workorder = visible_workorders_queryset(user).get(pk=int(object_id))
        except (ValueError, TypeError):
            raise ValidationError("Invalid workorder id.")
        except WorkOrder.DoesNotExist as exc:
            raise PermissionDenied("Workorder is not visible to the current user.") from exc
        transition_targets = [
            status for status, _label in WorkOrderStatus.choices if can_transition(user, workorder, status)
        ]
        summary["selection"] = {
            "source_code": "workorders",
            "object_type": "workorder",
            "object_id": str(workorder.pk),
            "number": workorder.number,
            "title": workorder.title,
            "status": workorder.status,
            "status_label": workorder.get_status_display(),
            "priority": workorder.priority,
            "priority_label": workorder.get_priority_display(),
            "department": str(workorder.department),
            "device": workorder.device.name if workorder.device_id else "",
            "assignee": workorder.assignee.get_username() if workorder.assignee_id else "",
            "updated_at": workorder.updated_at.isoformat() if workorder.updated_at else "",
        }
        summary["capabilities"] = {
            "can_comment": can_comment(user, workorder),
            "can_confirm_closure": can_confirm_closure(user, workorder),
            "can_rate": can_rate(user, workorder),
            "transition_targets": transition_targets,
        }
        summary["context_hint"] = f"workorders / {workorder.number}"
        return summary

    summary["selection"] = {
        "source_code": source_code,
        "object_type": object_type,
        "object_id": object_id,
        "display": selection.get("display", ""),
        "resolved": False,
    }
    return summary


def update_window_context_snapshot(user, envelope: dict[str, Any]) -> ContextUpdateResult:
    sanitized = sanitize_page_context_envelope(envelope)
    resolved = resolve_page_context(user, sanitized)
    context_hash = stable_context_hash({"page": sanitized, "resolved": resolved})
    window_id = sanitized["window_id"]
    current = (
        AIWindowContextSnapshot.objects.filter(user=user, window_id=window_id, is_current=True)
        .order_by("-context_version", "-id")
        .first()
    )
    if current and current.context_hash == context_hash and current.expires_at > timezone.now():
        return ContextUpdateResult(snapshot=current, created=False)
    next_version = (current.context_version + 1) if current else 1
    AIWindowContextSnapshot.objects.filter(user=user, window_id=window_id, is_current=True).update(is_current=False)
    snapshot = AIWindowContextSnapshot.objects.create(
        user=user,
        window_id=window_id,
        context_version=next_version,
        context_hash=context_hash,
        sanitized_envelope={**sanitized, "context_version": next_version},
        resolved_summary=resolved,
        is_current=True,
        expires_at=timezone.now() + timezone.timedelta(hours=PAGE_CONTEXT_TTL_HOURS),
    )
    return ContextUpdateResult(snapshot=snapshot, created=True)


def bind_page_context_to_message(*, user, message: ChatMessage, window_id: str = "", context_version: Any = "", context_hint: str = "") -> dict[str, Any]:
    metadata = dict(message.metadata or {})
    metadata["context_hint"] = _safe_string(context_hint, max_len=200)
    metadata["page_context_present"] = bool(window_id or context_version or context_hint)
    metadata["window_id"] = _safe_string(window_id, max_len=128)
    try:
        version_int = int(context_version)
    except (TypeError, ValueError):
        version_int = 0
    metadata["context_version"] = version_int
    if not window_id or not version_int:
        metadata["page_context_status"] = "missing"
        message.metadata = metadata
        message.save(update_fields=["metadata"])
        return metadata
    snapshot = (
        AIWindowContextSnapshot.objects.filter(
            user=user,
            window_id=window_id,
            context_version=version_int,
            expires_at__gt=timezone.now(),
        )
        .order_by("-id")
        .first()
    )
    if not snapshot:
        metadata["page_context_status"] = "context_stale"
        message.metadata = metadata
        message.save(update_fields=["metadata"])
        return metadata
    metadata.update(
        {
            "page_context_status": "bound",
            "context_snapshot_id": snapshot.id,
            "context_hash": snapshot.context_hash,
            "page_context_digest": digest_resolved_summary(snapshot.resolved_summary),
        }
    )
    message.metadata = metadata
    message.save(update_fields=["metadata"])
    return metadata


def get_bound_page_context_for_actor(actor_context: dict[str, Any]) -> dict[str, Any]:
    page_context = actor_context.get("page_context") if isinstance(actor_context, dict) else {}
    if not isinstance(page_context, dict):
        page_context = {}
    snapshot_id = page_context.get("context_snapshot_id") or actor_context.get("context_snapshot_id")
    user_id = actor_context.get("user_id")
    if not snapshot_id or not user_id:
        return {"status": "context_unavailable", "reason": "No context snapshot is bound to this request."}
    snapshot = (
        AIWindowContextSnapshot.objects.filter(pk=snapshot_id, user_id=user_id, expires_at__gt=timezone.now())
        .order_by("-id")
        .first()
    )
    if not snapshot:
        return {"status": "context_stale", "reason": "The bound context snapshot is unavailable or expired."}
    return {
        "status": "ok",
        "context_snapshot_id": snapshot.id,
        "window_id": snapshot.window_id,
        "context_version": snapshot.context_version,
        "context_hash": snapshot.context_hash,
        "context": snapshot.resolved_summary,
    }


def build_runtime_page_context(message: ChatMessage | None) -> dict[str, Any]:
    metadata = dict(getattr(message, "metadata", {}) or {})
    return {
        "page_context_present": bool(metadata.get("page_context_present")),
        "page_context_status": metadata.get("page_context_status", ""),
        "context_snapshot_id": metadata.get("context_snapshot_id"),
        "window_id": metadata.get("window_id", ""),
        "context_version": metadata.get("context_version") or 0,
        "context_hash": metadata.get("context_hash", ""),
        "context_hint": metadata.get("context_hint", ""),
        "digest": metadata.get("page_context_digest") or {},
    }


def digest_resolved_summary(summary: dict[str, Any]) -> dict[str, Any]:
    page = summary.get("page") or {}
    selection = summary.get("selection") or {}
    return {
        "module": page.get("module", ""),
        "view": page.get("view", ""),
        "object_type": selection.get("object_type", ""),
        "object_id_hash": hashlib.sha256(str(selection.get("object_id", "")).encode("utf-8")).hexdigest()[:16]
        if selection.get("object_id")
        else "",
        "source_code": selection.get("source_code", ""),
        "context_hint": summary.get("context_hint", ""),
    }


def build_context_hint(envelope: dict[str, Any]) -> str:
    page = envelope.get("page") or {}
    selection = envelope.get("selection") or {}
    if selection.get("source_code") and selection.get("object_id"):
        return f"{selection.get('source_code')} / {selection.get('object_type')}#{selection.get('object_id')}"
    module = page.get("module") or "page"
    view = page.get("view") or page.get("title") or ""
    return f"{module} / {view}".strip(" /")


def stable_context_hash(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _sanitize_mapping(value: Any, allowed_keys: set[str] | None, *, max_value_len: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    clean = {}
    for key, item in value.items():
        key_text = _safe_string(key, max_len=80)
        if not key_text or (allowed_keys is not None and key_text not in allowed_keys):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            clean[key_text] = _safe_string(item, max_len=max_value_len) if not isinstance(item, bool) else item
    return clean


def _safe_string(value: Any, *, max_len: int) -> str:
    text = str(value or "").strip()
    text = SAFE_TEXT_RE.sub("", text)
    return text[:max_len]
