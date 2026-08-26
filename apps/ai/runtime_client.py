import httpx
from django.conf import settings


class AgentRuntimeError(Exception):
    pass


class AgentRuntimeClient:
    def __init__(self):
        self.base_url = settings.LOCAL_BUSINESS_AGENT_RUNTIME_URL.rstrip("/")
        self.ag_ui_url = settings.LOCAL_BUSINESS_AGENT_RUNTIME_AG_UI_URL

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
