from mcp.server.fastmcp import FastMCP

from .config import load_runtime_settings
from .gateway_client import DjangoGatewayClient


def build_mcp_server() -> FastMCP:
    mcp = FastMCP(
        "Корпоративный портал ВОБ №3 MCP",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    def gateway_client() -> DjangoGatewayClient:
        settings = load_runtime_settings()
        return DjangoGatewayClient(
            base_url=settings.django_gateway_url,
            token=settings.django_gateway_token,
        )

    @mcp.tool()
    def workorders_list(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        status: str = "",
        limit: int = 20,
    ):
        """List work orders visible to the current user."""
        result = gateway_client().execute_tool(
            tool_code="workorders.list",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={"status": status or None, "limit": limit},
            session_id=session_id,
        )
        return result

    @mcp.tool()
    def workorders_get(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        workorder_id: int | None = None,
        number: str | None = None,
    ):
        """Get one work order by internal id or business number."""
        result = gateway_client().execute_tool(
            tool_code="workorders.get",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={"workorder_id": workorder_id, "number": number},
            session_id=session_id,
        )
        return result

    @mcp.tool()
    def workorders_create(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        department_id: int,
        subject: str,
        description: str,
        priority: str = "medium",
    ):
        """Create a work order for the current user."""
        result = gateway_client().execute_tool(
            tool_code="workorders.create",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={
                "department_id": department_id,
                "subject": subject,
                "description": description,
                "priority": priority,
            },
            session_id=session_id,
        )
        return result

    @mcp.tool()
    def workorders_transition(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        workorder_id: int,
        target_status: str,
    ):
        """Transition a work order to a target status."""
        result = gateway_client().execute_tool(
            tool_code="workorders.transition",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={"workorder_id": workorder_id, "target_status": target_status},
            session_id=session_id,
        )
        return result

    @mcp.tool()
    def workorders_comment(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        workorder_id: int,
        text: str,
    ):
        """Add a comment to a work order."""
        result = gateway_client().execute_tool(
            tool_code="workorders.comment",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={"workorder_id": workorder_id, "text": text},
            session_id=session_id,
        )
        return result

    @mcp.tool()
    def departments_list(
        user_id: int, username: str, roles: list[str], session_id: str, query: str = ""
    ):
        """List departments for lookup and selection."""
        result = gateway_client().execute_tool(
            tool_code="departments.list",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={"query": query},
            session_id=session_id,
        )
        return result

    @mcp.tool()
    def devices_list(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        query: str = "",
        department_id: int | None = None,
    ):
        """List devices for lookup and selection."""
        result = gateway_client().execute_tool(
            tool_code="devices.list",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={"query": query, "department_id": department_id},
            session_id=session_id,
        )
        return result

    return mcp
