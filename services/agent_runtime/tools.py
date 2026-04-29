from langchain.tools import tool

from .gateway_client import DjangoGatewayClient


def build_tools(
    *,
    actor: dict,
    session_id: str,
    gateway_client: DjangoGatewayClient,
    conversation_id: str = "",
    request_id: str = "",
    origin_channel: str = "",
    actor_version: str = "",
):
    """
    Build LangChain tools with identity/correlation context.

    All tools forward the trace context (conversation_id, request_id,
    origin_channel, actor_version) to the Django gateway for audit persistence.
    """

    @tool("workorders.list")
    def list_workorders(status: str = "", limit: int = 20) -> dict:
        """List work orders visible to the current user, optionally filtered by status."""
        result = gateway_client.execute_tool(
            tool_code="workorders.list",
            actor=actor,
            payload={"status": status or None, "limit": limit},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("workorders.get")
    def get_workorder(workorder_id: int | None = None, number: str | None = None) -> dict:
        """Get one work order by internal id or business number."""
        result = gateway_client.execute_tool(
            tool_code="workorders.get",
            actor=actor,
            payload={"workorder_id": workorder_id, "number": number},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("workorders.create")
    def create_workorder(department_id: int, subject: str, description: str, priority: str = "medium") -> dict:
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
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("workorders.transition")
    def transition_workorder(workorder_id: int, target_status: str) -> dict:
        """Move a work order to a target status if policy allows."""
        result = gateway_client.execute_tool(
            tool_code="workorders.transition",
            actor=actor,
            payload={"workorder_id": workorder_id, "target_status": target_status},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("workorders.comment")
    def comment_workorder(workorder_id: int, text: str) -> dict:
        """Add a comment to a work order."""
        result = gateway_client.execute_tool(
            tool_code="workorders.comment",
            actor=actor,
            payload={"workorder_id": workorder_id, "text": text},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("departments.list")
    def list_departments(query: str = "") -> dict:
        """List departments for selection and lookup."""
        result = gateway_client.execute_tool(
            tool_code="departments.list",
            actor=actor,
            payload={"query": query},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("devices.list")
    def list_devices(query: str = "", department_id: int | None = None) -> dict:
        """List devices for selection and lookup."""
        result = gateway_client.execute_tool(
            tool_code="devices.list",
            actor=actor,
            payload={"query": query, "department_id": department_id},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("access.update_role_permissions")
    def update_role_permissions(role_name: str, permissions_map: dict) -> dict:
        """
        Updates permissions for a specific role. 
        Example permissions_map: {"create_workorder": true, "view_scope": "all"}.
        Requires administrator privileges.
        """
        result = gateway_client.execute_tool(
            tool_code="access.update_role_permissions",
            actor=actor,
            payload={"role_name": role_name, "permissions_map": permissions_map},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("access.get_role_rules")
    def get_role_rules() -> dict:
        """
        Returns the current role and permission configuration from the system.
        Use this to see what permissions roles currently have.
        """
        result = gateway_client.execute_tool(
            tool_code="access.get_role_rules",
            actor=actor,
            payload={},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("access.users.list")
    def list_users(query: str = "") -> dict:
        """
        Returns a list of users with their roles and departments.
        Requires administrator privileges.
        """
        result = gateway_client.execute_tool(
            tool_code="access.users.list",
            actor=actor,
            payload={"query": query},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("access.users.update")
    def update_user(user_id: int, is_active: bool | None = None, department_id: int | None = None, group_names: list[str] | None = None) -> dict:
        """
        Updates user details. Use this to change user groups, department or activation status.
        Requires administrator privileges.
        """
        result = gateway_client.execute_tool(
            tool_code="access.users.update",
            actor=actor,
            payload={
                "user_id": user_id,
                "is_active": is_active,
                "department_id": department_id,
                "group_names": group_names
            },
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("access.groups.list")
    def list_groups() -> dict:
        """
        Returns a list of all security groups available in the system.
        Requires administrator privileges.
        """
        result = gateway_client.execute_tool(
            tool_code="access.groups.list",
            actor=actor,
            payload={},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    return [
        list_workorders,
        get_workorder,
        create_workorder,
        transition_workorder,
        comment_workorder,
        list_departments,
        list_devices,
        update_role_permissions,
        get_role_rules,
        list_users,
        update_user,
        list_groups,
    ]
