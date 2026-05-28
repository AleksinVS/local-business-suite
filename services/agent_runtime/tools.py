from langchain.tools import tool

from .gateway_client import DjangoGatewayClient
from .task_types import normalize_status, normalize_priority


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
    """
    current_session_id = session_id

    @tool("ui.get_current_context")
    def get_current_context() -> dict:
        """
        Return the safe server-resolved context for the current browser window.

        Use this when the user says "эта заявка", "текущая карточка",
        "здесь", "этот документ" or asks a question that depends on the
        current page, selected drawer object or active module.
        """
        result = gateway_client.execute_tool(
            tool_code="ui.get_current_context",
            actor=actor,
            payload={},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("workorders.list")
    def list_workorders(status: str = "", limit: int = 20) -> dict:
        """List work orders visible to the current user, optionally filtered by status."""
        if status:
            status = normalize_status(status)
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
        priority = normalize_priority(priority)
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
        target_status = normalize_status(target_status)
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

    @tool("memory.search")
    def search_memory(
        query: str,
        limit: int = 5,
        sensitivity: str = "internal",
        search_mode: str = "knowledge_default",
        ranking_profile: str = "",
        include_source_data: bool = False,
    ) -> dict:
        """
        Search the safe memory corpus for cited context available to the current user.

        Use this for questions about the memory service, indexed knowledge,
        remembered context, source citations, previous safe context, or facts
        linked to work orders/devices. Use source_explicit when the user asks
        to search original indexed files or source documents. Use
        ranking_profile=source_content for exact source content and
        ranking_profile=source_semantic for meaning-based source file search.
        Use source_fallback when source documents are acceptable if accepted
        knowledge is empty, and knowledge_semantic for semantic accepted
        knowledge search. The tool returns only safe chunks/facts with citations;
        it does not expose raw snapshots or accepted knowledge for source_data.
        """
        result = gateway_client.execute_tool(
            tool_code="memory.search",
            actor=actor,
            payload={
                "query": query,
                "limit": limit,
                "sensitivity": sensitivity,
                "search_mode": search_mode,
                "ranking_profile": ranking_profile,
                "include_source_data": include_source_data,
            },
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("memory.remember")
    def remember_memory(
        session_id: str = "",
        message_ids: list[int] | None = None,
        target_scope: str = "personal",
        user_note: str = "",
        importance: str = "",
    ) -> dict:
        """
        Queue selected chat knowledge for memory ingestion.

        Use this when the user explicitly asks to remember something. If no
        message_ids are provided, the Django memory service uses the current
        chat session and the latest user message or user_note. The default
        target_scope is personal; use organization only when the user clearly
        asked to remember this for everyone or for the organization.
        """
        result = gateway_client.execute_tool(
            tool_code="memory.remember",
            actor=actor,
            payload={
                "session_id": session_id or current_session_id,
                "message_ids": message_ids or [],
                "target_scope": target_scope or "personal",
                "user_note": user_note,
                "importance": importance,
            },
            session_id=session_id or current_session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("memory.update_personal")
    def update_personal_memory(memory_id: str, operation: str, new_text: str = "") -> dict:
        """
        Edit or delete one personal memory item owned by the current user.

        Use this when the user asks to correct or forget a specific personal
        memory item. If the memory_id is unknown, search memory first and ask
        the user to confirm the item before changing it.
        """
        result = gateway_client.execute_tool(
            tool_code="memory.update_personal",
            actor=actor,
            payload={"memory_id": memory_id, "operation": operation, "new_text": new_text},
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )
        return result

    @tool("access.update_role_permissions")
    def update_role_permissions(role_name: str, permissions_map: dict) -> dict:
        """Updates permissions for a specific role. Requires administrator privileges."""
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
        """Returns current role and permission configuration. Useful before making changes."""
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
        """Returns a list of users with roles and departments. Requires administrator privileges."""
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
        """Updates user details. Requires administrator privileges."""
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
        """Returns a list of all security groups. Requires administrator privileges."""
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

    @tool("activate_skill")
    def activate_skill(skill_id: str) -> dict:
        """
        Activates a specific skill by loading its instructions.
        Use this when a user's request requires specific knowledge (e.g. access management).
        """
        result = gateway_client.load_skill_content(skill_id)
        if "error" in result:
            return {"ok": False, "error": result["error"]}
        
        return {
            "ok": True, 
            "skill_id": skill_id, 
            "instructions": result["instructions"],
            "message": f"Skill '{skill_id}' activated. I have updated my instructions."
        }

    return [
        get_current_context,
        list_workorders,
        get_workorder,
        create_workorder,
        transition_workorder,
        comment_workorder,
        list_departments,
        list_devices,
        search_memory,
        remember_memory,
        update_personal_memory,
        update_role_permissions,
        get_role_rules,
        list_users,
        update_user,
        list_groups,
        activate_skill,
    ]
