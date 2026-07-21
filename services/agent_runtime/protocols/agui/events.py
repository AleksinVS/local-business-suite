import json
import time
from typing import Any

from services.agent_runtime.protocols.common.capabilities import protocol_metadata_value


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


def timestamp() -> int:
    return int(time.time() * 1000)


def event(event_type: str, **payload: Any) -> dict[str, Any]:
    return {"type": event_type, "timestamp": timestamp(), **payload}


def sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def run_started_event(run_input, *, include_input: bool = False) -> dict[str, Any]:
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
    return event(EVENT_RUN_STARTED, **payload)


def protocol_metadata_event(*, driver: str = "") -> dict[str, Any]:
    return event(
        EVENT_CUSTOM,
        name="local_business.protocol",
        value=protocol_metadata_value(driver=driver),
    )


def run_finished_event(run_input, *, result: dict[str, Any] | None = None) -> dict[str, Any]:
    return event(
        EVENT_RUN_FINISHED,
        threadId=run_input.threadId,
        runId=run_input.runId,
        outcome={"type": "success"},
        result=result or {},
    )


def run_error_event(message: str, *, code: str = "agent_runtime_error") -> dict[str, Any]:
    return event(EVENT_RUN_ERROR, message=message, code=code)
