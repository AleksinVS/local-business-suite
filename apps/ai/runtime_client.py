import uuid

import httpx
from django.conf import settings


class AgentRuntimeError(Exception):
    pass


class AgentRuntimeClient:
    def __init__(self):
        self.base_url = settings.LOCAL_BUSINESS_AGENT_RUNTIME_URL.rstrip("/")
        self.timeout = settings.LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT

    def chat(
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
    ):
        """
        Send a chat message to the LangGraph agent runtime.

        Identity/correlation fields (conversation_id, request_id, origin_channel,
        actor_version) are propagated through the runtime pipeline and persisted
        in the audit trail. They are generated here if not supplied, so every
        request has trace context from the Django chat surface onward.
        """
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        if not request_id:
            request_id = str(uuid.uuid4())
        if not origin_channel:
            origin_channel = "django-chat"

        payload = {
            "session_id": str(session_id),
            "prompt": prompt,
            "history": history,
            "actor": {
                "user_id": user.id,
                "username": user.username,
                "roles": list(user.groups.values_list("name", flat=True)),
                "is_superuser": user.is_superuser,
                "channel": "internal",
                "source": "django-chat",
                "conversation_id": conversation_id,
                "request_id": request_id,
                "origin_channel": origin_channel,
                "actor_version": actor_version,
            },
        }
        try:
            response = httpx.post(
                f"{self.base_url}/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AgentRuntimeError(str(exc)) from exc
        data = response.json()
        if "assistant_message" not in data:
            raise AgentRuntimeError("Agent runtime returned invalid payload.")
        # Always carry trace context back in the response for storage
        data["conversation_id"] = conversation_id
        data["request_id"] = request_id
        return data

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
            "actor": {
                "user_id": user.id,
                "username": user.username,
                "roles": list(user.groups.values_list("name", flat=True)),
                "is_superuser": user.is_superuser,
                "channel": "internal",
                "source": "django-chat",
                "conversation_id": conversation_id,
                "request_id": request_id,
                "origin_channel": origin_channel,
                "actor_version": actor_version,
            },
        }
        
        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/stream",
            json=payload,
            timeout=self.timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    yield line
