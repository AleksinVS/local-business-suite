import httpx


class DjangoGatewayClient:
    def __init__(self, *, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def execute_tool(self, *, tool_code: str, actor: dict, payload: dict, session_id: str) -> dict:
        response = httpx.post(
            f"{self.base_url}/tools/{tool_code}/execute/",
            json={
                "actor": actor,
                "payload": payload,
                "session_id": session_id,
            },
            headers={"X-AI-Gateway-Token": self.token},
            timeout=90,
        )
        response.raise_for_status()
        return response.json()
