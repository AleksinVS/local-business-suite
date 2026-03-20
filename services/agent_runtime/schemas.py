from typing import Any

from pydantic import BaseModel, Field


class ActorContext(BaseModel):
    user_id: int
    username: str
    roles: list[str] = Field(default_factory=list)
    is_superuser: bool = False
    channel: str = "internal"
    source: str = "chat"


class HistoryMessage(BaseModel):
    role: str
    content: str
    tool_name: str = ""


class ChatRequest(BaseModel):
    session_id: str
    prompt: str
    actor: ActorContext
    history: list[HistoryMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session_id: str
    assistant_message: str
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
