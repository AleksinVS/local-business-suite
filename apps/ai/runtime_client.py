import uuid

import httpx
from django.conf import settings


class AgentRuntimeError(Exception):
    pass


class AgentRuntimeClient:
    def __init__(self):
        self.base_url = settings.LOCAL_BUSINESS_AGENT_RUNTIME_URL.rstrip("/")
        self.ag_ui_url = settings.LOCAL_BUSINESS_AGENT_RUNTIME_AG_UI_URL

    def chat_stream(
        self,
        *,
        user,
        session_id,
        prompt,
        history,
        conversation_id: str = "",
        request_id: str = "",
        origin_channel: str = "",
        actor_version: str = "",
        model_id: str = "",
        page_context: dict | None = None,
    ):
        """
        Stream chat messages from the LangGraph agent runtime.
        Returns a generator of SSE events.
        """
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        if not request_id:
            request_id = str(uuid.uuid4())
        if not origin_channel:
            origin_channel = "django-chat-stream"

        payload = {
            "session_id": str(session_id),
            "prompt": prompt,
            "history": history,
            "model_id": model_id,
            "actor": {
                "user_id": user.id,
                "username": user.username,
                "roles": list(user.groups.values_list("name", flat=True)),
                "is_superuser": user.is_superuser,
                "channel": origin_channel or "internal",
                "source": "django-chat",
                "conversation_id": conversation_id,
                "request_id": request_id,
                "origin_channel": origin_channel,
                "actor_version": actor_version,
            },
        }
        if page_context:
            payload["actor"]["page_context"] = page_context
            payload["actor"]["context_snapshot_id"] = page_context.get("context_snapshot_id")
            payload["actor"]["context_hint"] = page_context.get("context_hint", "")
        
        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/stream",
            json=payload,
            timeout=httpx.Timeout(
                connect=30.0,
                read=settings.LOCAL_BUSINESS_AI_STREAM_READ_TIMEOUT,
                write=30.0,
                pool=30.0,
            ),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    yield line

    def ag_ui_stream(self, payload: dict):
        """
        Stream AG-UI-compatible events from the agent runtime.

        This is used by the native AI UI driver through a same-origin Django
        proxy. CopilotKit still uses the dedicated Copilot Runtime service.
        """
        with httpx.stream(
            "POST",
            self.ag_ui_url,
            json=payload,
            timeout=httpx.Timeout(
                connect=30.0,
                read=settings.LOCAL_BUSINESS_AI_STREAM_READ_TIMEOUT,
                write=30.0,
                pool=30.0,
            ),
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_text():
                if chunk:
                    yield chunk
