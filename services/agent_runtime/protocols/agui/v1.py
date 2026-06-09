import json
import uuid
from collections.abc import Iterable
from typing import Any

from services.agent_runtime.protocols.common.ui_commands import normalize_ui_commands
from services.agent_runtime.schemas import AGUIRunAgentInput, HistoryMessage

from .events import (
    EVENT_CUSTOM,
    EVENT_STATE_DELTA,
    EVENT_TEXT_MESSAGE_CONTENT,
    EVENT_TEXT_MESSAGE_END,
    EVENT_TEXT_MESSAGE_START,
    EVENT_TOOL_CALL_ARGS,
    EVENT_TOOL_CALL_END,
    EVENT_TOOL_CALL_RESULT,
    EVENT_TOOL_CALL_START,
    event,
    protocol_metadata_event,
    run_error_event,
    run_finished_event,
    run_started_event,
    sse_event,
)


def text_message_events(chunks: Iterable[str], *, message_id: str | None = None) -> Iterable[dict[str, Any]]:
    message_id = message_id or f"msg_{uuid.uuid4().hex}"
    started = False
    for chunk in chunks:
        if not chunk:
            continue
        if not started:
            started = True
            yield event(EVENT_TEXT_MESSAGE_START, messageId=message_id, role="assistant")
        yield event(EVENT_TEXT_MESSAGE_CONTENT, messageId=message_id, delta=str(chunk))
    if started:
        yield event(EVENT_TEXT_MESSAGE_END, messageId=message_id)


def safe_tool_args(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in args.items():
        lowered = str(key).lower()
        if any(token in lowered for token in ("token", "secret", "password", "cookie", "credential")):
            safe[key] = "[redacted]"
        else:
            safe[key] = value
    return safe


def tool_trace_events(
    tool_trace: list[dict[str, Any]],
    *,
    parent_message_id: str,
) -> Iterable[dict[str, Any]]:
    for index, trace_item in enumerate(tool_trace, start=1):
        tool_name = str(trace_item.get("tool") or "tool")
        tool_call_id = str(trace_item.get("tool_call_id") or f"tool_{index}_{uuid.uuid4().hex[:8]}")
        args = safe_tool_args(trace_item.get("args"))
        yield event(
            EVENT_TOOL_CALL_START,
            toolCallId=tool_call_id,
            toolCallName=tool_name,
            parentMessageId=parent_message_id,
        )
        yield event(
            EVENT_TOOL_CALL_ARGS,
            toolCallId=tool_call_id,
            delta=json.dumps(args, ensure_ascii=False, separators=(",", ":")),
        )
        yield event(EVENT_TOOL_CALL_END, toolCallId=tool_call_id)
        yield event(
            EVENT_TOOL_CALL_RESULT,
            messageId=f"tool_result_{tool_call_id}",
            toolCallId=tool_call_id,
            role="tool",
            content=json.dumps({"status": "completed"}, ensure_ascii=False),
        )


def ui_command_events(ui_commands: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    safe_commands = normalize_ui_commands(ui_commands)
    if not safe_commands:
        return
    yield event(
        EVENT_STATE_DELTA,
        delta=[
            {
                "op": "replace",
                "path": "/localBusiness/uiCommands",
                "value": safe_commands,
            },
            {
                "op": "replace",
                "path": "/localBusinessUiCommands",
                "value": safe_commands,
            },
        ],
    )
    for command in safe_commands:
        yield event(EVENT_CUSTOM, name="local_business.ui_command", value=command)


def agui_history(run_input: AGUIRunAgentInput) -> list[HistoryMessage]:
    return run_input.history_messages()


def agui_prompt(run_input: AGUIRunAgentInput) -> str:
    return run_input.latest_user_text()
