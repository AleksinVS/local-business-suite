import httpx
from django.conf import settings


class AgentRuntimeError(Exception):
    pass


class AgentRuntimeClient:
    def __init__(self):
        self.base_url = settings.LOCAL_BUSINESS_AGENT_RUNTIME_URL.rstrip("/")
        self.timeout = settings.LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT

    def chat(self, *, user, session_id, prompt, history):
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
        return data
