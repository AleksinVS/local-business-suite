from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.workorders.models import WorkOrder

from .models import AgentActionLog, ChatMessage, PendingAction
from .page_context import get_bound_page_context_for_actor
from .services import (
    append_chat_message,
    add_comment_for_actor,
    archive_device_for_actor,
    confirm_closure_for_actor,
    create_device_for_actor,
    create_workorder_for_actor,
    get_workorder_for_actor,
    get_or_create_session,
    list_departments_for_actor,
    list_devices_for_actor,
    list_workorders_for_actor,
    rate_workorder_for_actor,
    record_action,
    resolve_actor,
    transition_workorder_for_actor,
    update_device_for_actor,
    get_analytics_summary_for_actor,
    get_waiting_list_entry_for_actor,
)
from .tool_definitions import get_tool_registry


class UnknownToolError(Exception):
    pass


# ADR-0030 decision 6: memory.search's public contract no longer accepts a
# ranking profile, a search mode, an include_source_data toggle, or raw
# channel weights — only corpus (knowledge/source_data) + limit. Keep an
# explicit reject list so a caller that still sends the old parameters gets a
# clear ValidationError instead of the value being silently dropped.
_MEMORY_SEARCH_REMOVED_KEYS = {
    "search_mode",
    "ranking_profile",
    "include_source_data",
    "fulltext_weight",
    "vector_weight",
    "graph_weight",
}

_MEMORY_SEARCH_CORPUS_VALUES = {"knowledge", "source_data"}


def _normalize_memory_search_corpus(value) -> str:
    corpus = str(value or "knowledge").strip()
    if corpus not in _MEMORY_SEARCH_CORPUS_VALUES:
        raise ValidationError(f"Unsupported memory.search corpus: {corpus!r}.")
    return corpus


# Bounded-scope task type registry imported lazily to avoid circular imports.
_task_type_catalog = None


def _get_task_type_catalog():
    global _task_type_catalog
    if _task_type_catalog is None:
        from services.agent_runtime.task_types import get_all_bounded_task_types
        _task_type_catalog = get_all_bounded_task_types()
    return _task_type_catalog


def tool_registry():
    return get_tool_registry()


def _build_task_type_report(tool_code: str, payload: dict) -> dict:
    """
    Build a machine-readable task_type_report for the bounded scope.
    Returns an empty dict if the tool is outside the bounded scope.
    """
    catalog = _get_task_type_catalog()
    for contract in catalog.values():
        if tool_code in contract.allowed_tools:
            missing = contract.get_missing_required_slots(payload)
            return {
                "task_type_id": contract.id,
                "task_type_title": contract.title,
                "task_type_mode": contract.mode.value,
                "required_slots": list(contract.required_slots),
                "fulfilled_slots": list(contract.get_fulfilled_slots(payload).keys()),
                "missing_required_slots": missing,
                "all_slots_fulfilled": len(missing) == 0,
                "requires_confirmation": contract.requires_confirmation,
            }
    return {}


def _build_command_context(*, tool_code, action_kind, actor, session, payload, trace_context, confirmation_state):
    return {
        "tool_code": tool_code,
        "action_kind": action_kind,
        "actor_id": actor.pk if actor else None,
        "session_id": str(session.external_id) if session else "",
        "conversation_id": trace_context.get("conversation_id", ""),
        "request_id": trace_context.get("request_id", ""),
        "origin_channel": trace_context.get("origin_channel", ""),
        "confirmation_state": confirmation_state,
        "payload_keys": sorted(str(key) for key in (payload or {}).keys()),
    }


def _dispatch_tool(*, tool_code, actor, session, actor_context, payload, user_message):
    """Execute the tool logic and return the result dict or raise an exception."""
    if tool_code == "ui.get_current_context":
        return get_bound_page_context_for_actor(actor_context)
    if tool_code == "ui.open_right_panel":
        from apps.core.right_panels import build_right_panel_descriptor

        mode = payload.get("mode", "view") or "view"
        if mode != "view":
            raise ValidationError("ui.open_right_panel поддерживает только режим просмотра.")
        descriptor = build_right_panel_descriptor(
            user=actor,
            source_code=payload.get("source_code", ""),
            object_type=payload.get("object_type", ""),
            object_id=payload.get("object_id", ""),
            mode=mode,
        )
        return {
            "status": "ok",
            "message": "Right panel command is ready.",
            "ui_command": descriptor.as_dict(),
        }
    if tool_code == "workorders.list":
        return {
            "items": list_workorders_for_actor(
                actor=actor,
                status=payload.get("status"),
                limit=payload.get("limit", 20),
            )
        }
    elif tool_code == "workorders.get":
        return {
            "workorder": get_workorder_for_actor(
                actor=actor,
                workorder_id=payload.get("workorder_id"),
                number=payload.get("number"),
            )
        }
    elif tool_code == "workorders.search":
        from apps.memory.retrieval import memory_search

        return memory_search(
            actor=actor,
            query=payload.get("query"),
            sensitivity="internal",
            limit=payload.get("limit", 5),
            request_id=actor_context.get("request_id", ""),
            search_mode="source_explicit",
            include_source_data=True,
            ranking_profile="source_content",
            source_codes=["workorders"],
        )
    elif tool_code == "waiting_list.get":
        return {
            "entry": get_waiting_list_entry_for_actor(
                actor=actor,
                entry_id=payload.get("entry_id"),
            )
        }
    elif tool_code == "workorders.create":
        return create_workorder_for_actor(actor=actor, payload=payload)
    elif tool_code == "workorders.transition":
        return transition_workorder_for_actor(actor=actor, payload=payload)
    elif tool_code == "workorders.comment":
        return {"comment": add_comment_for_actor(actor=actor, payload=payload)}
    elif tool_code == "workorders.confirm_closure":
        return confirm_closure_for_actor(actor=actor, payload=payload)
    elif tool_code == "workorders.rate":
        return rate_workorder_for_actor(actor=actor, payload=payload)
    elif tool_code == "departments.list":
        return {"items": list_departments_for_actor(actor=actor, query=payload.get("query", ""), parent_id=payload.get("parent_id"))}
    elif tool_code == "devices.list":
        return {
            "items": list_devices_for_actor(
                actor=actor,
                query=payload.get("query", ""),
                department_id=payload.get("department_id"),
                archived=payload.get("archived", False),
            )
        }
    elif tool_code == "inventory.devices.create":
        return {"device": create_device_for_actor(actor=actor, payload=payload)}
    elif tool_code == "inventory.devices.update":
        return {"device": update_device_for_actor(actor=actor, payload=payload)}
    elif tool_code == "inventory.devices.archive":
        return {"device": archive_device_for_actor(actor=actor, payload=payload)}
    elif tool_code == "analytics.summary":
        return get_analytics_summary_for_actor(actor=actor, payload=payload)
    elif tool_code == "memory.search":
        from apps.memory.retrieval import memory_search

        # ADR-0030 decision 6: the public memory.search contract exposes only
        # corpus + limit (see apps/ai/tool_definitions.py, contracts/ai/tools.json).
        # ranking_profile/search_mode/include_source_data and raw channel
        # weights were removed from the public surface; reject them explicitly
        # rather than silently ignoring a caller that still sends them.
        removed_keys = _MEMORY_SEARCH_REMOVED_KEYS & set(payload.keys())
        if removed_keys:
            raise ValidationError(
                "memory.search больше не принимает параметры выбора профиля/весов ранжирования: "
                f"{', '.join(sorted(removed_keys))}. Публичный контракт сокращен до corpus и limit "
                "(ADR-0030 решение 6; профили ранжирования ADR-0016 — отложенный долг)."
            )
        corpus = _normalize_memory_search_corpus(payload.get("corpus"))
        return memory_search(
            actor=actor,
            query=payload.get("query"),
            sensitivity=payload.get("sensitivity"),
            limit=payload.get("limit", 5),
            request_id=actor_context.get("request_id", ""),
            search_mode="source_explicit" if corpus == "source_data" else "knowledge_default",
        )
    elif tool_code == "memory.remember":
        from apps.memory.services import remember_knowledge_for_actor

        return remember_knowledge_for_actor(
            actor=actor,
            session=session,
            payload=payload,
            request_id=actor_context.get("request_id", ""),
        )
    elif tool_code == "memory.update_personal":
        from apps.memory.services import update_personal_memory_for_actor

        return update_personal_memory_for_actor(actor=actor, payload=payload)
    elif tool_code == "ai.skills.create_or_update":
        from .skill_authoring import create_or_update_runtime_skill_for_actor

        return create_or_update_runtime_skill_for_actor(actor=actor, payload=payload)
    elif tool_code == "access.get_role_rules":
        from .services import get_role_rules_for_actor
        return get_role_rules_for_actor(actor=actor, payload=payload)
    elif tool_code == "access.users.list":
        from .services import list_users_for_actor
        return list_users_for_actor(actor=actor, payload=payload)
    elif tool_code == "access.users.explain":
        from .services import explain_user_access_for_actor
        return explain_user_access_for_actor(actor=actor, payload=payload)
    elif tool_code == "access.open_editor":
        from .services import open_access_editor_for_actor
        return open_access_editor_for_actor(actor=actor, payload=payload)
    elif tool_code == "access.groups.list":
        from .services import list_groups_for_actor
        return list_groups_for_actor(actor=actor, payload=payload)
    else:
        raise UnknownToolError(tool_code)


def execute_tool(
    *,
    tool_code,
    actor_context,
    payload,
    session_external_id=None,
    confirmed_token=None,
    conversation_id="",
    request_id="",
    origin_channel="",
    actor_version="",
):
    # Confirmation is an explicit state transition handled by
    # execute_pending_action().  This legacy argument is retained only for
    # callers that still pass it; it must never turn an arbitrary request
    # payload into an approved write.  In particular, a missing/invalid token
    # fails closed before creating a session, audit record, or pending action.
    if confirmed_token:
        raise ValidationError(
            "Подтверждение выполняется только через сохранённое ожидающее действие."
        )

    registry = tool_registry()
    if tool_code not in registry:
        raise UnknownToolError(tool_code)
    tool = registry[tool_code]
    actor = resolve_actor(
        user_id=actor_context.get("user_id"),
        username=actor_context.get("username"),
    )
    session = get_or_create_session(
        user=actor,
        session_external_id=session_external_id,
        channel=actor_context.get("channel", "internal"),
    )

    # Persist conversation_id in session metadata for traceability.
    if conversation_id and session.metadata.get("conversation_id") != conversation_id:
        session.metadata = {
            **session.metadata,
            "conversation_id": conversation_id,
            "request_ids": [*session.metadata.get("request_ids", []), request_id],
        }
        session.save(update_fields=["metadata", "updated_at"])

    # Build trace context metadata to persist across all audit structures.
    trace_context = {
        "conversation_id": conversation_id,
        "request_id": request_id,
        "origin_channel": origin_channel,
        "actor_version": actor_version,
        "page_context_present": bool((actor_context.get("page_context") or {}).get("page_context_present")),
        "context_snapshot_id": (actor_context.get("page_context") or {}).get("context_snapshot_id"),
        "context_hint": (actor_context.get("page_context") or {}).get("context_hint", actor_context.get("context_hint", "")),
        "context_tool_called": tool_code == "ui.get_current_context",
    }

    user_message = None
    if actor_context.get("user_prompt"):
        user_message = append_chat_message(
            session=session,
            role=ChatMessage.Role.USER,
            content=actor_context["user_prompt"],
            metadata={**{"source": actor_context.get("source", "chat")}, **trace_context},
        )

    requires_confirmation = tool.get("requires_confirmation", False)
    confirmation_preview = None

    confirmation_state = "not_required"
    if requires_confirmation and not confirmed_token:
        confirmation_state = "pending_required"
    elif confirmed_token:
        confirmation_state = "confirmed_token"

    command_context = _build_command_context(
        tool_code=tool_code,
        action_kind=tool["mode"],
        actor=actor,
        session=session,
        payload=payload,
        trace_context=trace_context,
        confirmation_state=confirmation_state,
    )

    audit_request_payload = _build_audit_request_payload(
        tool_code=tool_code,
        payload=payload,
        trace_context=trace_context,
        command_context=command_context,
    )

    if requires_confirmation and not confirmed_token:
        pending = PendingAction.objects.create(
            tool_code=tool_code,
            action_kind=tool["mode"],
            actor=actor,
            session=session,
            payload=payload,
            status=PendingAction.Status.PENDING,
        )
        record_action(
            actor=actor,
            tool_code=tool_code,
            action_kind=tool["mode"],
            status=AgentActionLog.Status.PENDING,
            request_payload=audit_request_payload,
            response_payload={**trace_context, "pending_token": str(pending.token)},
            session=session,
            message=user_message,
        )
        task_report = _build_task_type_report(tool_code, payload)
        return {
            "ok": True,
            "tool": tool_code,
            "result": None,
            "errors": [],
            "meta": {
                "session_id": str(session.external_id),
                "pending_action_token": str(pending.token),
                "awaiting_confirmation": True,
                **({"confirmation_preview": confirmation_preview} if confirmation_preview else {}),
                **trace_context,
                **({"task_type_report": task_report} if task_report else {}),
            },
        }

    try:
        result = _dispatch_tool(
            tool_code=tool_code,
            actor=actor,
            session=session,
            actor_context={**actor_context, **trace_context},
            payload=payload,
            user_message=user_message,
        )
        append_chat_message(
            session=session,
            role=ChatMessage.Role.TOOL,
            content=f"Tool {tool_code} executed successfully.",
            tool_name=tool_code,
            metadata={**{"result_preview": result}, **trace_context},
        )
        record_action(
            actor=actor,
            tool_code=tool_code,
            action_kind=tool["mode"],
            status=AgentActionLog.Status.SUCCEEDED,
            request_payload=audit_request_payload,
            response_payload={**trace_context, **result},
            session=session,
            message=user_message,
        )
        task_report = _build_task_type_report(tool_code, payload)
        return {
            "ok": True,
            "tool": tool_code,
            "result": result,
            "errors": [],
            "meta": {
                "session_id": str(session.external_id),
                **trace_context,
                **({"task_type_report": task_report} if task_report else {}),
            },
        }
    except PermissionDenied as exc:
        record_action(
            actor=actor,
            tool_code=tool_code,
            action_kind=tool["mode"],
            status=AgentActionLog.Status.DENIED,
            request_payload=audit_request_payload,
            response_payload={"error": str(exc), **trace_context},
            session=session,
            message=user_message,
            error_message=str(exc),
        )
        task_report = _build_task_type_report(tool_code, payload)
        return {
            "ok": False,
            "tool": tool_code,
            "result": None,
            "errors": [str(exc)],
            "meta": {
                "session_id": str(session.external_id),
                **trace_context,
                **({"task_type_report": task_report} if task_report else {}),
            },
        }
    except (ValidationError, KeyError, WorkOrder.DoesNotExist) as exc:
        record_action(
            actor=actor,
            tool_code=tool_code,
            action_kind=tool["mode"],
            status=AgentActionLog.Status.FAILED,
            request_payload=audit_request_payload,
            response_payload={"error": str(exc), **trace_context},
            session=session,
            message=user_message,
            error_message=str(exc),
        )
        task_report = _build_task_type_report(tool_code, payload)
        return {
            "ok": False,
            "tool": tool_code,
            "result": None,
            "errors": [str(exc)],
            "meta": {
                "session_id": str(session.external_id),
                **trace_context,
                **({"task_type_report": task_report} if task_report else {}),
            },
        }
    except Exception as exc:
        record_action(
            actor=actor,
            tool_code=tool_code,
            action_kind=tool["mode"],
            status=AgentActionLog.Status.FAILED,
            request_payload=audit_request_payload,
            response_payload={"error": str(exc), **trace_context},
            session=session,
            message=user_message,
            error_message=str(exc),
        )
        task_report = _build_task_type_report(tool_code, payload)
        return {
            "ok": False,
            "tool": tool_code,
            "result": None,
            "errors": [str(exc)],
            "meta": {
                "session_id": str(session.external_id),
                **trace_context,
                **({"task_type_report": task_report} if task_report else {}),
            },
        }


def execute_pending_action(
    *,
    token,
    confirmed,
    actor_context,
    session_external_id=None,
    conversation_id="",
    request_id="",
    origin_channel="",
    actor_version="",
):
    """
    Execute or cancel a pending action by token.

    When confirmed=True, the pending action is replayed using the stored payload
    and actor, then marked CONFIRMED.
    When confirmed=False, the pending action is marked CANCELLED.

    Identity/correlation fields are propagated into the audit trail.
    """
    # Use the token parameter directly (from URL in confirm flow).
    # This is the primary lookup key when called from the confirm endpoint.
    if not token:
        # Fallback: try to get from actor_context for replay scenarios
        # where execute_tool calls this with token=None
        token = actor_context.get("token")

    pending = None
    dispatch_succeeded = False
    try:
        # Транзакция защищает только одноразовое занятие действия. Исполнение
        # намеренно идёт после commit: инструменты могут атомарно писать файлы и
        # обязаны сначала зафиксировать собственную pending-запись аудита.
        with transaction.atomic():
            pending = (
                PendingAction.objects.select_related("actor", "session")
                .filter(token=token)
                .first()
            )
            error = _validate_pending_action_owner(
                pending=pending,
                actor_context=actor_context,
                session_external_id=session_external_id,
            )
            if error:
                return error

            trace_context = {
                "conversation_id": conversation_id,
                "request_id": request_id,
                "origin_channel": origin_channel,
                "actor_version": actor_version,
            }
            command_context = _build_command_context(
                tool_code=pending.tool_code,
                action_kind=pending.action_kind,
                actor=pending.actor,
                session=pending.session,
                payload=pending.payload,
                trace_context=trace_context,
                confirmation_state="confirmed" if confirmed else "cancelled",
            )
            audit_request_payload = _build_audit_request_payload(
                tool_code=pending.tool_code,
                payload=pending.payload,
                trace_context=trace_context,
                command_context=command_context,
            )
            audit_request_payload["pending_token"] = str(pending.token)

            if not confirmed:
                now = timezone.now()
                claimed = PendingAction.objects.filter(
                    pk=pending.pk,
                    status=PendingAction.Status.PENDING,
                ).update(status=PendingAction.Status.CANCELLED, updated_at=now)
                if claimed != 1:
                    pending.refresh_from_db()
                    return _pending_action_status_conflict(pending)
                pending.status = PendingAction.Status.CANCELLED
                record_action(
                    actor=pending.actor,
                    tool_code=pending.tool_code,
                    action_kind=pending.action_kind,
                    status=AgentActionLog.Status.DENIED,
                    request_payload=audit_request_payload,
                    response_payload={},
                    session=pending.session,
                    message=None,
                    error_message="Cancelled by user.",
                )
            elif not tool_registry().get(pending.tool_code):
                now = timezone.now()
                claimed = PendingAction.objects.filter(
                    pk=pending.pk,
                    status=PendingAction.Status.PENDING,
                ).update(status=PendingAction.Status.FAILED, updated_at=now)
                if claimed != 1:
                    pending.refresh_from_db()
                    return _pending_action_status_conflict(pending)
                pending.status = PendingAction.Status.FAILED
                record_action(
                    actor=pending.actor,
                    tool_code=pending.tool_code,
                    action_kind=pending.action_kind,
                    status=AgentActionLog.Status.FAILED,
                    request_payload=audit_request_payload,
                    response_payload={"error": "Tool no longer available.", **trace_context},
                    session=pending.session,
                    message=None,
                    error_message="Tool no longer available.",
                )
                return {
                    "ok": False,
                    "tool": pending.tool_code,
                    "result": None,
                    "errors": [f"Tool {pending.tool_code} no longer available."],
                    "meta": {"pending_action_status": pending.status},
                }
            else:
                now = timezone.now()
                processing_expires_at = now + timezone.timedelta(hours=1)
                claimed = PendingAction.objects.filter(
                    pk=pending.pk,
                    status=PendingAction.Status.PENDING,
                ).update(
                    status=PendingAction.Status.PROCESSING,
                    processing_started_at=now,
                    processing_expires_at=processing_expires_at,
                    updated_at=now,
                )
                if claimed != 1:
                    pending.refresh_from_db()
                    return _pending_action_status_conflict(pending)
                pending.status = PendingAction.Status.PROCESSING
                pending.processing_started_at = now
                pending.processing_expires_at = processing_expires_at

        if not confirmed:
            return _pending_action_response(
                pending=pending,
                trace_context=trace_context,
                ok=True,
                result=None,
            )

        try:
            result = _dispatch_tool(
                tool_code=pending.tool_code,
                actor=pending.actor,
                session=pending.session,
                actor_context={**actor_context, **trace_context},
                payload=pending.payload,
                user_message=None,
            )
            dispatch_succeeded = True
        except Exception as exc:
            known_no_effect = isinstance(
                exc,
                (PermissionDenied, ValidationError, KeyError, WorkOrder.DoesNotExist),
            )
            audit_status = (
                AgentActionLog.Status.DENIED
                if isinstance(exc, PermissionDenied)
                else AgentActionLog.Status.FAILED
            )
            with transaction.atomic():
                terminal = PendingAction.objects.select_for_update().get(pk=pending.pk)
                if terminal.status == PendingAction.Status.PROCESSING:
                    terminal.status = (
                        PendingAction.Status.FAILED
                        if known_no_effect
                        else PendingAction.Status.RECONCILIATION_REQUIRED
                    )
                    terminal.save(update_fields=["status", "updated_at"])
                record_action(
                    actor=pending.actor,
                    tool_code=pending.tool_code,
                    action_kind=pending.action_kind,
                    status=audit_status,
                    request_payload=audit_request_payload,
                    response_payload={"error": str(exc), **trace_context},
                    session=pending.session,
                    message=None,
                    error_message=str(exc),
                )
            pending.status = terminal.status
            return _pending_action_response(
                pending=pending,
                trace_context=trace_context,
                ok=False,
                result=None,
                errors=[str(exc)],
            )

        _finalize_pending_action_success(
            pending=pending,
            result=result,
            trace_context=trace_context,
            audit_request_payload=audit_request_payload,
        )
        pending.status = PendingAction.Status.CONFIRMED
        return _pending_action_response(
            pending=pending,
            trace_context=trace_context,
            ok=True,
            result=result,
        )
    except Exception as exc:
        if dispatch_succeeded and pending is not None:
            _record_pending_action_reconciliation(
                pending=pending,
                result=result,
                error=exc,
                trace_context=trace_context,
                audit_request_payload=audit_request_payload,
            )
            pending.status = PendingAction.Status.RECONCILIATION_REQUIRED
        return {
            "ok": False,
            "tool": pending.tool_code if pending is not None else None,
            "result": None,
            "errors": [f"Unexpected error processing pending action: {str(exc)}"],
            "meta": (
                {"pending_action_status": pending.status}
                if pending is not None
                else {}
            ),
        }


def _finalize_pending_action_success(*, pending, result, trace_context, audit_request_payload):
    """Атомарно завершить исполнение и записать его предметный аудит."""
    with transaction.atomic():
        terminal = PendingAction.objects.select_for_update().get(pk=pending.pk)
        if terminal.status != PendingAction.Status.PROCESSING:
            raise RuntimeError("Статус выполняемого действия изменился до завершения.")
        terminal.status = PendingAction.Status.CONFIRMED
        terminal.save(update_fields=["status", "updated_at"])
        record_action(
            actor=pending.actor,
            tool_code=pending.tool_code,
            action_kind=pending.action_kind,
            status=AgentActionLog.Status.SUCCEEDED,
            request_payload=audit_request_payload,
            response_payload={**trace_context, **result},
            session=pending.session,
            message=None,
        )
        if pending.session:
            append_chat_message(
                session=pending.session,
                role=ChatMessage.Role.TOOL,
                content=f"Tool {pending.tool_code} executed after confirmation.",
                tool_name=pending.tool_code,
                metadata={
                    "result_preview": result,
                    "pending_token": str(pending.token),
                    **trace_context,
                },
            )


def _record_pending_action_reconciliation(
    *, pending, result, error, trace_context, audit_request_payload
):
    """Зафиксировать неопределённый итог после уже выполненного побочного эффекта."""
    try:
        with transaction.atomic():
            PendingAction.objects.filter(
                pk=pending.pk,
                status__in=(
                    PendingAction.Status.PROCESSING,
                    PendingAction.Status.RECONCILIATION_REQUIRED,
                ),
            ).update(
                status=PendingAction.Status.RECONCILIATION_REQUIRED,
                updated_at=timezone.now(),
            )
            record_action(
                actor=pending.actor,
                tool_code=pending.tool_code,
                action_kind=pending.action_kind,
                status=AgentActionLog.Status.FAILED,
                request_payload=audit_request_payload,
                response_payload={
                    **trace_context,
                    "dispatch_succeeded": True,
                    "reconciliation_required": True,
                    "result_preview": result,
                },
                session=pending.session,
                message=None,
                error_message=f"Terminal audit failed after dispatch: {error}",
            )
    except Exception:
        # Даже если вторичный аудит временно недоступен, статус остаётся
        # главным сигналом для операционной сверки при следующем восстановлении.
        PendingAction.objects.filter(
            pk=pending.pk,
            status=PendingAction.Status.PROCESSING,
        ).update(
            status=PendingAction.Status.RECONCILIATION_REQUIRED,
            updated_at=timezone.now(),
        )


def _pending_action_status_conflict(pending):
    return {
        "ok": False,
        "tool": pending.tool_code,
        "result": None,
        "errors": [f"Ожидающее действие уже имеет статус {pending.get_status_display()}."],
        "meta": {"pending_action_status": pending.status},
    }


def _validate_pending_action_owner(*, pending, actor_context, session_external_id):
    if not pending:
        return {
            "ok": False,
            "tool": None,
            "result": None,
            "errors": ["Ожидающее действие не найдено или уже обработано."],
            "meta": {},
        }
    if pending.status != PendingAction.Status.PENDING:
        return {
            "ok": False,
            "tool": pending.tool_code,
            "result": None,
            "errors": [f"Ожидающее действие уже имеет статус {pending.get_status_display()}."],
            "meta": {"pending_action_status": pending.status},
        }
    if pending.expires_at <= timezone.now():
        pending.status = PendingAction.Status.EXPIRED
        pending.save(update_fields=["status", "updated_at"])
        return {
            "ok": False,
            "tool": pending.tool_code,
            "result": None,
            "errors": ["Срок ожидания действия истек."],
            "meta": {"pending_action_status": pending.status},
        }
    actor_user_id = actor_context.get("user_id")
    if not actor_user_id:
        return {
            "ok": False,
            "tool": pending.tool_code,
            "result": None,
            "errors": ["Для подтверждения требуется идентификатор пользователя."],
            "meta": {"pending_action_status": pending.status},
        }
    if str(actor_user_id) != str(pending.actor_id):
        return {
            "ok": False,
            "tool": pending.tool_code,
            "result": None,
            "errors": ["Actor does not own this pending action."],
            "meta": {"pending_action_status": pending.status},
        }
    if session_external_id:
        from .services import normalize_session_external_id

        normalized_session_id = normalize_session_external_id(session_external_id)
        if pending.session and pending.session.external_id != normalized_session_id:
            return {
                "ok": False,
                "tool": pending.tool_code,
                "result": None,
                "errors": ["Session does not own this pending action."],
                "meta": {"pending_action_status": pending.status},
            }
    return None


def _pending_action_response(*, pending, trace_context, ok, result, errors=None):
    task_report = _build_task_type_report(pending.tool_code, pending.payload)
    return {
        "ok": ok,
        "tool": pending.tool_code,
        "result": result,
        "errors": errors or [],
        "meta": {
            "pending_action_token": str(pending.token),
            "pending_action_status": pending.status,
            "session_id": str(pending.session.external_id) if pending.session else None,
            **trace_context,
            **({"task_type_report": task_report} if task_report else {}),
        },
    }


def _build_audit_request_payload(*, tool_code, payload, trace_context, command_context=None):
    safe_payload = dict(payload or {})
    if tool_code in {"memory.remember", "memory.update_personal"}:
        for key in ("user_note", "new_text"):
            if key in safe_payload:
                safe_payload[key] = _redact_secret_like_text(str(safe_payload.get(key) or ""))
    if tool_code == "ai.skills.create_or_update":
        if "body" in safe_payload:
            safe_payload["body"] = f"<SKILL_BODY_REDACTED:length={len(str(payload.get('body') or ''))}>"
        if "instructions" in safe_payload:
            safe_payload["instructions"] = f"<SKILL_BODY_REDACTED:length={len(str(payload.get('instructions') or ''))}>"
        if "frontmatter" in safe_payload and isinstance(safe_payload["frontmatter"], dict):
            safe_payload["frontmatter"] = {
                key: value
                for key, value in safe_payload["frontmatter"].items()
                if key in {"name", "description", "source_code", "object_types", "required_tools", "trigger_examples"}
            }
    audit_payload = {**trace_context, **safe_payload}
    if command_context:
        audit_payload["command"] = command_context
    return audit_payload


def _redact_secret_like_text(text: str) -> str:
    try:
        from apps.memory.security import scan_for_secrets

        findings = scan_for_secrets(text).findings
    except Exception:
        return text
    if not findings:
        return text
    output = []
    cursor = 0
    for finding in sorted(findings, key=lambda item: item.start):
        output.append(text[cursor:finding.start])
        output.append("<SECRET_REDACTED>")
        cursor = finding.end
    output.append(text[cursor:])
    return "".join(output)
