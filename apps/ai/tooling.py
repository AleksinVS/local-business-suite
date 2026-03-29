from django.core.exceptions import PermissionDenied, ValidationError

from apps.workorders.models import WorkOrder

from .models import AgentActionLog, ChatMessage, PendingAction
from .services import (
    append_chat_message,
    add_comment_for_actor,
    create_workorder_for_actor,
    get_workorder_for_actor,
    get_or_create_session,
    list_departments_for_actor,
    list_devices_for_actor,
    list_workorders_for_actor,
    record_action,
    resolve_actor,
    transition_workorder_for_actor,
)
from .tool_definitions import get_tool_registry


class UnknownToolError(Exception):
    pass


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


def _dispatch_tool(*, tool_code, actor, session, actor_context, payload, user_message):
    """Execute the tool logic and return the result dict or raise an exception."""
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
    elif tool_code == "workorders.create":
        return create_workorder_for_actor(actor=actor, payload=payload)
    elif tool_code == "workorders.transition":
        return transition_workorder_for_actor(actor=actor, payload=payload)
    elif tool_code == "workorders.comment":
        return {"comment": add_comment_for_actor(actor=actor, payload=payload)}
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
        session.metadata["conversation_id"] = conversation_id
        if "request_ids" not in session.metadata:
            session.metadata["request_ids"] = []
        session.metadata["request_ids"].append(request_id)
        session.save(update_fields=["metadata", "updated_at"])

    # Build trace context metadata to persist across all audit structures.
    trace_context = {
        "conversation_id": conversation_id,
        "request_id": request_id,
        "origin_channel": origin_channel,
        "actor_version": actor_version,
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

    # Handle explicit token replay for confirmed pending actions
    if confirmed_token:
        pending = PendingAction.objects.filter(
            token=confirmed_token,
            tool_code=tool_code,
            actor=actor,
        ).first()
        if pending:
            requires_confirmation = False  # replay confirmed pending action

    # Augment request_payload with trace context for audit trail
    audit_request_payload = {**trace_context, **payload}

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
                **trace_context,
                **({"task_type_report": task_report} if task_report else {}),
            },
        }

    try:
        result = _dispatch_tool(
            tool_code=tool_code,
            actor=actor,
            session=session,
            actor_context=actor_context,
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
            response_payload={},
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
            response_payload={},
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
    pending = PendingAction.objects.filter(token=token).first()
    if not pending:
        return {
            "ok": False,
            "tool": None,
            "result": None,
            "errors": ["Pending action not found or already resolved."],
            "meta": {},
        }

    if pending.status != PendingAction.Status.PENDING:
        return {
            "ok": False,
            "tool": pending.tool_code,
            "result": None,
            "errors": [f"Pending action is already {pending.status}."],
            "meta": {"pending_action_status": pending.status},
        }

    trace_context = {
        "conversation_id": conversation_id,
        "request_id": request_id,
        "origin_channel": origin_channel,
        "actor_version": actor_version,
    }
    audit_request_payload = {**trace_context, **pending.payload}

    if confirmed:
        registry = tool_registry()
        tool = registry.get(pending.tool_code)
        if not tool:
            pending.status = PendingAction.Status.CANCELLED
            pending.save(update_fields=["status", "updated_at"])
            return {
                "ok": False,
                "tool": pending.tool_code,
                "result": None,
                "errors": [f"Tool {pending.tool_code} no longer available."],
                "meta": {},
            }

        try:
            result = _dispatch_tool(
                tool_code=pending.tool_code,
                actor=pending.actor,
                session=pending.session,
                actor_context=actor_context,
                payload=pending.payload,
                user_message=None,
            )
        except PermissionDenied as exc:
            record_action(
                actor=pending.actor,
                tool_code=pending.tool_code,
                action_kind=pending.action_kind,
                status=AgentActionLog.Status.DENIED,
                request_payload=audit_request_payload,
                response_payload={},
                session=pending.session,
                message=None,
                error_message=str(exc),
            )
            return {
                "ok": False,
                "tool": pending.tool_code,
                "result": None,
                "errors": [str(exc)],
                "meta": {
                    "pending_action_token": str(pending.token),
                    "pending_action_status": pending.status,
                    **trace_context,
                },
            }
        except (ValidationError, KeyError, WorkOrder.DoesNotExist) as exc:
            record_action(
                actor=pending.actor,
                tool_code=pending.tool_code,
                action_kind=pending.action_kind,
                status=AgentActionLog.Status.FAILED,
                request_payload=audit_request_payload,
                response_payload={},
                session=pending.session,
                message=None,
                error_message=str(exc),
            )
            return {
                "ok": False,
                "tool": pending.tool_code,
                "result": None,
                "errors": [str(exc)],
                "meta": {
                    "pending_action_token": str(pending.token),
                    "pending_action_status": pending.status,
                    **trace_context,
                },
            }

        # Mark CONFIRMED only after successful execution
        pending.status = PendingAction.Status.CONFIRMED
        pending.save(update_fields=["status", "updated_at"])

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
                metadata={**{"result_preview": result, "pending_token": str(pending.token)}, **trace_context},
            )

        task_report = _build_task_type_report(pending.tool_code, pending.payload)
        return {
            "ok": True,
            "tool": pending.tool_code,
            "result": result,
            "errors": [],
            "meta": {
                "pending_action_token": str(pending.token),
                "pending_action_status": pending.status,
                "session_id": str(pending.session.external_id) if pending.session else None,
                **trace_context,
                **({"task_type_report": task_report} if task_report else {}),
            },
        }
    else:
        pending.status = PendingAction.Status.CANCELLED
        pending.save(update_fields=["status", "updated_at"])

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

        task_report = _build_task_type_report(pending.tool_code, pending.payload)
        return {
            "ok": True,
            "tool": pending.tool_code,
            "result": None,
            "errors": [],
            "meta": {
                "pending_action_token": str(pending.token),
                "pending_action_status": pending.status,
                "session_id": str(pending.session.external_id) if pending.session else None,
                **trace_context,
                **({"task_type_report": task_report} if task_report else {}),
            },
        }
