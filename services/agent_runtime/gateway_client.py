import httpx


class DjangoGatewayClient:
    def __init__(self, *, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def execute_tool(
        self,
        *,
        tool_code: str,
        actor: dict,
        payload: dict,
        session_id: str,
        conversation_id: str = "",
        request_id: str = "",
        origin_channel: str = "",
        actor_version: str = "",
    ) -> dict:
        """
        Execute a tool via the Django AI gateway.
        """
        request_payload = {
            "actor": actor,
            "payload": payload,
            "session_id": session_id,
        }
        if conversation_id:
            request_payload["conversation_id"] = conversation_id
        if request_id:
            request_payload["request_id"] = request_id
        if origin_channel:
            request_payload["origin_channel"] = origin_channel
        if actor_version:
            request_payload["actor_version"] = actor_version

        response = httpx.post(
            f"{self.base_url}/gateway/tools/{tool_code}/execute/",
            json=request_payload,
            headers={"X-AI-Gateway-Token": self.token},
            timeout=90,
        )
        response.raise_for_status()
        return response.json()

    def get_skills_catalog(self):
        """Fetches the available skills catalog from Django."""
        try:
            response = httpx.get(
                f"{self.base_url}/gateway/skills/catalog/",
                headers={"X-AI-Gateway-Token": self.token},
                timeout=10.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            return {"skills": []}

    def load_skill_content(self, skill_id):
        """Loads specific skill instructions from Django."""
        try:
            response = httpx.get(
                f"{self.base_url}/gateway/skills/{skill_id}/load/",
                headers={"X-AI-Gateway-Token": self.token},
                timeout=10.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            return {"error": str(exc)}
