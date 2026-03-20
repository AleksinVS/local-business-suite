from langchain.tools import tool

from .gateway_client import DjangoGatewayClient


def build_tools(*, actor: dict, session_id: str, gateway_client: DjangoGatewayClient):
    @tool("workorders.list")
    def list_workorders(status: str = "", limit: int = 20) -> str:
        """List work orders visible to the current user, optionally filtered by status."""
        result = gateway_client.execute_tool(
            tool_code="workorders.list",
            actor=actor,
            payload={"status": status or None, "limit": limit},
            session_id=session_id,
        )
        return str(result["result"])

    @tool("workorders.get")
    def get_workorder(workorder_id: int | None = None, number: str | None = None) -> str:
        """Get one work order by internal id or business number."""
        result = gateway_client.execute_tool(
            tool_code="workorders.get",
            actor=actor,
            payload={"workorder_id": workorder_id, "number": number},
            session_id=session_id,
        )
        return str(result["result"])

    @tool("workorders.create")
    def create_workorder(department_id: int, subject: str, description: str, priority: str = "medium") -> str:
        """Create a work order for the current user."""
        result = gateway_client.execute_tool(
            tool_code="workorders.create",
            actor=actor,
            payload={
                "department_id": department_id,
                "subject": subject,
                "description": description,
                "priority": priority,
            },
            session_id=session_id,
        )
        return str(result["result"])

    @tool("workorders.transition")
    def transition_workorder(workorder_id: int, target_status: str) -> str:
        """Move a work order to a target status if policy allows."""
        result = gateway_client.execute_tool(
            tool_code="workorders.transition",
            actor=actor,
            payload={"workorder_id": workorder_id, "target_status": target_status},
            session_id=session_id,
        )
        return str(result["result"])

    @tool("workorders.comment")
    def comment_workorder(workorder_id: int, text: str) -> str:
        """Add a comment to a work order."""
        result = gateway_client.execute_tool(
            tool_code="workorders.comment",
            actor=actor,
            payload={"workorder_id": workorder_id, "text": text},
            session_id=session_id,
        )
        return str(result["result"])

    @tool("departments.list")
    def list_departments(query: str = "") -> str:
        """List departments for selection and lookup."""
        result = gateway_client.execute_tool(
            tool_code="departments.list",
            actor=actor,
            payload={"query": query},
            session_id=session_id,
        )
        return str(result["result"])

    @tool("devices.list")
    def list_devices(query: str = "", department_id: int | None = None) -> str:
        """List devices for lookup and selection."""
        result = gateway_client.execute_tool(
            tool_code="devices.list",
            actor=actor,
            payload={"query": query, "department_id": department_id},
            session_id=session_id,
        )
        return str(result["result"])

    return [
        list_workorders,
        get_workorder,
        create_workorder,
        transition_workorder,
        comment_workorder,
        list_departments,
        list_devices,
    ]
