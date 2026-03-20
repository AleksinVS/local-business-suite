from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError

from .models import AgentActionLog, ChatMessage
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


class UnknownToolError(Exception):
    pass


def tool_registry():
    return {item["id"]: item for item in settings.LOCAL_BUSINESS_AI_TOOLS["tools"]}


def execute_tool(*, tool_code, actor_context, payload, session_external_id=None):
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
    user_message = None
    if actor_context.get("user_prompt"):
        user_message = append_chat_message(
            session=session,
            role=ChatMessage.Role.USER,
            content=actor_context["user_prompt"],
            metadata={"source": actor_context.get("source", "chat")},
        )

    try:
        if tool_code == "workorders.list":
            result = {
                "items": list_workorders_for_actor(
                    actor=actor,
                    status=payload.get("status"),
                    limit=payload.get("limit", 20),
                )
            }
        elif tool_code == "workorders.get":
            result = {
                "workorder": get_workorder_for_actor(
                    actor=actor,
                    workorder_id=payload.get("workorder_id"),
                    number=payload.get("number"),
                )
            }
        elif tool_code == "workorders.create":
            result = create_workorder_for_actor(actor=actor, payload=payload)
        elif tool_code == "workorders.transition":
            result = transition_workorder_for_actor(actor=actor, payload=payload)
        elif tool_code == "workorders.comment":
            result = {"comment": add_comment_for_actor(actor=actor, payload=payload)}
        elif tool_code == "departments.list":
            result = {"items": list_departments_for_actor(actor=actor, query=payload.get("query", ""), parent_id=payload.get("parent_id"))}
        elif tool_code == "devices.list":
            result = {
                "items": list_devices_for_actor(
                    actor=actor,
                    query=payload.get("query", ""),
                    department_id=payload.get("department_id"),
                    archived=payload.get("archived", False),
                )
            }
        else:
            raise UnknownToolError(tool_code)
        append_chat_message(
            session=session,
            role=ChatMessage.Role.TOOL,
            content=f"Tool {tool_code} executed successfully.",
            tool_name=tool_code,
            metadata={"result_preview": result},
        )
        record_action(
            actor=actor,
            tool_code=tool_code,
            action_kind=tool["mode"],
            status=AgentActionLog.Status.SUCCEEDED,
            request_payload=payload,
            response_payload=result,
            session=session,
            message=user_message,
        )
        return {"session_id": str(session.external_id), "tool": tool_code, "result": result}
    except PermissionDenied as exc:
        record_action(
            actor=actor,
            tool_code=tool_code,
            action_kind=tool["mode"],
            status=AgentActionLog.Status.DENIED,
            request_payload=payload,
            response_payload={},
            session=session,
            message=user_message,
            error_message=str(exc),
        )
        raise
    except (ValidationError, KeyError) as exc:
        record_action(
            actor=actor,
            tool_code=tool_code,
            action_kind=tool["mode"],
            status=AgentActionLog.Status.FAILED,
            request_payload=payload,
            response_payload={},
            session=session,
            message=user_message,
            error_message=str(exc),
        )
        raise
