import json
import time
import uuid
from collections.abc import Iterable
from typing import Any

from .schemas import AGUIRunAgentInput, HistoryMessage


EVENT_RUN_STARTED = "RUN_STARTED"
EVENT_RUN_FINISHED = "RUN_FINISHED"
EVENT_RUN_ERROR = "RUN_ERROR"
EVENT_TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
EVENT_TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
EVENT_TEXT_MESSAGE_END = "TEXT_MESSAGE_END"
EVENT_TOOL_CALL_START = "TOOL_CALL_START"
EVENT_TOOL_CALL_ARGS = "TOOL_CALL_ARGS"
EVENT_TOOL_CALL_END = "TOOL_CALL_END"
EVENT_TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
EVENT_STATE_DELTA = "STATE_DELTA"
EVENT_CUSTOM = "CUSTOM"


def _timestamp() -> int:
    return int(time.time() * 1000)


def _event(event_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": event_type, "timestamp": _timestamp(), **payload}


def sse_event(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"


def run_started_event(run_input: AGUIRunAgentInput, *, include_input: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "threadId": run_input.threadId,
        "runId": run_input.runId,
    }
    if run_input.parentRunId:
        payload["parentRunId"] = run_input.parentRunId
    if include_input:
        payload["input"] = {
            "threadId": run_input.threadId,
            "runId": run_input.runId,
            "messages": [
                {"id": item.id, "role": item.role, "content": item.content}
                for item in run_input.messages
                if item.role in {"user", "assistant", "tool"}
            ],
            "state": {},
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
    return _event(EVENT_RUN_STARTED, **payload)


def run_finished_event(
    run_input: AGUIRunAgentInput,
    *,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _event(
        EVENT_RUN_FINISHED,
        threadId=run_input.threadId,
        runId=run_input.runId,
        outcome={"type": "success"},
        result=result or {},
    )


def run_error_event(message: str, *, code: str = "agent_runtime_error") -> dict[str, Any]:
    return _event(EVENT_RUN_ERROR, message=message, code=code)


def text_message_events(chunks: Iterable[str], *, message_id: str | None = None) -> Iterable[dict[str, Any]]:
    message_id = message_id or f"msg_{uuid.uuid4().hex}"
    started = False
    for chunk in chunks:
        if not chunk:
            continue
        if not started:
            started = True
            yield _event(EVENT_TEXT_MESSAGE_START, messageId=message_id, role="assistant")
        yield _event(EVENT_TEXT_MESSAGE_CONTENT, messageId=message_id, delta=str(chunk))
    if started:
        yield _event(EVENT_TEXT_MESSAGE_END, messageId=message_id)


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
        yield _event(
            EVENT_TOOL_CALL_START,
            toolCallId=tool_call_id,
            toolCallName=tool_name,
            parentMessageId=parent_message_id,
        )
        yield _event(
            EVENT_TOOL_CALL_ARGS,
            toolCallId=tool_call_id,
            delta=json.dumps(args, ensure_ascii=False, separators=(",", ":")),
        )
        yield _event(EVENT_TOOL_CALL_END, toolCallId=tool_call_id)
        yield _event(
            EVENT_TOOL_CALL_RESULT,
            messageId=f"tool_result_{tool_call_id}",
            toolCallId=tool_call_id,
            role="tool",
            content=json.dumps({"status": "completed"}, ensure_ascii=False),
        )


def ui_command_events(ui_commands: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    safe_commands = []
    for command in ui_commands:
        if not isinstance(command, dict):
            continue
        if command.get("type") != "open_right_panel":
            continue
        htmx_url = str(command.get("htmx_url") or command.get("url") or "")
        if not htmx_url.startswith("/") or htmx_url.startswith("//"):
            continue
        safe_commands.append(
            {
                "type": "open_right_panel",
                "source_code": command.get("source_code", ""),
                "object_type": command.get("object_type", ""),
                "object_id": str(command.get("object_id", "")),
                "mode": command.get("mode", "view"),
                "title": command.get("title", "Загрузка..."),
                "htmx_url": htmx_url,
                "target": "#global-right-panel-content",
                "swap": command.get("swap", "innerHTML"),
                "drawer_size": command.get("drawer_size", "default"),
            }
        )
    if not safe_commands:
        return
    yield _event(
        EVENT_STATE_DELTA,
        delta=[
            {
                "op": "replace",
                "path": "/localBusinessUiCommands",
                "value": safe_commands,
            }
        ],
    )
    for command in safe_commands:
        yield _event(EVENT_CUSTOM, name="local_business.ui_command", value=command)


def agui_history(run_input: AGUIRunAgentInput) -> list[HistoryMessage]:
    return run_input.history_messages()


def agui_prompt(run_input: AGUIRunAgentInput) -> str:
    return run_input.latest_user_text()
