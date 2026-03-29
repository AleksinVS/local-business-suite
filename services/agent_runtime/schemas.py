import uuid
from typing import Any

from pydantic import BaseModel, Field


class ActorContext(BaseModel):
    """Actor identity passed from Django chat surface through the runtime pipeline.

    Identity/correlation fields (conversation_id, request_id, origin_channel,
    actor_version) are propagated end-to-end and persisted into ChatSession.metadata,
    ChatMessage.metadata, and AgentActionLog.request_payload so the full trace from
    user prompt to tool execution can be correlated.
    """

    user_id: int
    username: str
    roles: list[str] = Field(default_factory=list)
    is_superuser: bool = False
    channel: str = "internal"
    source: str = "chat"
    # Trace / correlation fields — flow end-to-end from Django views to audit log.
    conversation_id: str = ""
    request_id: str = ""
    origin_channel: str = ""
    actor_version: str = ""

    def ensure_trace_context(self) -> "ActorContext":
        """Populate empty trace context fields with auto-generated values."""
        if not self.conversation_id:
            object.__setattr__(self, "conversation_id", str(uuid.uuid4()))
        if not self.request_id:
            object.__setattr__(self, "request_id", str(uuid.uuid4()))
        if not self.origin_channel:
            object.__setattr__(self, "origin_channel", self.channel)
        return self

    def trace_context(self) -> dict[str, str]:
        """Return only the correlation fields as a flat dict for propagation."""
        return {
            "conversation_id": self.conversation_id,
            "request_id": self.request_id,
            "origin_channel": self.origin_channel,
            "actor_version": self.actor_version,
        }


class HistoryMessage(BaseModel):
    role: str
    content: str
    tool_name: str = ""


class ChatRequest(BaseModel):
    session_id: str
    prompt: str
    actor: ActorContext
    history: list[HistoryMessage] = Field(default_factory=list)


class TaskTypeReport(BaseModel):
    """
    Machine-readable task-type resolution for the bounded scope
    (workorders.list, workorders.create, workorders.transition).

    Produced by the gateway tool execution layer and surfaced back through
    the runtime response so the Django surface can store it in the audit log.
    """

    task_type_id: str = ""
    task_type_title: str = ""
    task_type_mode: str = ""  # "read" | "write"
    required_slots: list[str] = Field(default_factory=list)
    fulfilled_slots: list[str] = Field(default_factory=list)
    missing_required_slots: list[str] = Field(default_factory=list)
    all_slots_fulfilled: bool = False
    requires_confirmation: bool = False


class ToolCallTrace(BaseModel):
    """Single tool call trace entry with task type resolution and slot state."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    task_type: TaskTypeReport = Field(default_factory=TaskTypeReport)
    resolved_tool: str = ""
    # Identity/correlation context propagated from the request
    conversation_id: str = ""
    request_id: str = ""
    origin_channel: str = ""
    actor_version: str = ""


class ChatResponse(BaseModel):
    session_id: str
    assistant_message: str
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    conversation_id: str = ""
    request_id: str = ""
    task_type_report: TaskTypeReport = Field(default_factory=TaskTypeReport)
