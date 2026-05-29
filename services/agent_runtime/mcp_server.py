from mcp.server.fastmcp import FastMCP

from .config import load_json, load_runtime_settings
from .gateway_client import DjangoGatewayClient
from .task_types import normalize_status, normalize_priority


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

    def tool_catalog() -> dict:
        settings = load_runtime_settings()
        return load_json(settings.ai_tools_path)

    def skills_catalog() -> list[dict]:
        return gateway_client().get_skills_catalog().get("skills", [])

    @mcp.resource(
        "local-business://skills/{skill_id}",
        name="AI skill metadata",
        description="Safe metadata for a module or runtime AI skill.",
        mime_type="application/json",
    )
    def skill_resource(skill_id: str):
        for item in skills_catalog():
            if item.get("id") == skill_id:
                return {
                    key: item.get(key)
                    for key in (
                        "id",
                        "name",
                        "description",
                        "source_code",
                        "object_types",
                        "required_tools",
                        "trigger_examples",
                        "registration_source",
                    )
                }
        return {"error": "skill_not_found", "skill_id": skill_id}

    @mcp.resource(
        "local-business://tools/{tool_code}",
        name="AI tool metadata",
        description="Safe metadata for a declared AI gateway tool.",
        mime_type="application/json",
    )
    def tool_resource(tool_code: str):
        for item in tool_catalog().get("tools", []):
            if item.get("id") == tool_code:
                return {
                    key: item.get(key)
                    for key in (
                        "id",
                        "title",
                        "domain",
                        "mode",
                        "execution_mode",
                        "description",
                        "inputs",
                        "outputs",
                        "requires_confirmation",
                        "required_role_scope",
                    )
                }
        return {"error": "tool_not_found", "tool_code": tool_code}

    @mcp.resource(
        "local-business://modules/{source_code}/capabilities",
        name="Module capabilities",
        description="Safe module capability summary derived from AI tools and skills.",
        mime_type="application/json",
    )
    def module_capabilities_resource(source_code: str):
        tools = [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "mode": item.get("mode"),
                "requires_confirmation": item.get("requires_confirmation", False),
            }
            for item in tool_catalog().get("tools", [])
            if item.get("domain") == source_code or str(item.get("id", "")).startswith(f"{source_code}.")
        ]
        skills = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "description": item.get("description"),
                "object_types": item.get("object_types", []),
                "required_tools": item.get("required_tools", []),
            }
            for item in skills_catalog()
            if item.get("source_code") == source_code
        ]
        return {"source_code": source_code, "tools": tools, "skills": skills}

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
        if status:
            status = normalize_status(status)
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
        priority = normalize_priority(priority)
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
        target_status = normalize_status(target_status)
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
    def workorders_delete(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        workorder_id: int,
    ):
        """Delete a visible work order if policy allows."""
        result = gateway_client().execute_tool(
            tool_code="workorders.delete",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={"workorder_id": workorder_id},
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

    @mcp.tool()
    def workorders_confirm_closure(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        workorder_id: int,
    ):
        """Confirm the closure of a resolved work order."""
        result = gateway_client().execute_tool(
            tool_code="workorders.confirm_closure",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={"workorder_id": workorder_id},
            session_id=session_id,
        )
        return result

    @mcp.tool()
    def workorders_rate(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        workorder_id: int,
        rating: int,
    ):
        """Rate a closed work order (1-5)."""
        result = gateway_client().execute_tool(
            tool_code="workorders.rate",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={"workorder_id": workorder_id, "rating": rating},
            session_id=session_id,
        )
        return result

    @mcp.tool()
    def inventory_devices_create(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        name: str,
        department_id: int,
        model: str = "",
        serial_number: str = "",
    ):
        """Create a new medical device in the inventory."""
        result = gateway_client().execute_tool(
            tool_code="inventory.devices.create",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={
                "name": name,
                "department_id": department_id,
                "model": model,
                "serial_number": serial_number,
            },
            session_id=session_id,
        )
        return result

    @mcp.tool()
    def inventory_devices_update(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        device_id: int,
        name: str | None = None,
        department_id: int | None = None,
        model: str | None = None,
        serial_number: str | None = None,
    ):
        """Update an existing medical device."""
        payload = {"device_id": device_id}
        if name is not None:
            payload["name"] = name
        if department_id is not None:
            payload["department_id"] = department_id
        if model is not None:
            payload["model"] = model
        if serial_number is not None:
            payload["serial_number"] = serial_number
        result = gateway_client().execute_tool(
            tool_code="inventory.devices.update",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload=payload,
            session_id=session_id,
        )
        return result

    @mcp.tool()
    def inventory_devices_archive(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        device_id: int,
    ):
        """Archive a medical device so it can no longer be assigned."""
        result = gateway_client().execute_tool(
            tool_code="inventory.devices.archive",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={"device_id": device_id},
            session_id=session_id,
        )
        return result

    @mcp.tool()
    def analytics_summary(
        user_id: int,
        username: str,
        roles: list[str],
        session_id: str,
        summary_type: str = "status",
    ):
        """Return analytics summaries for status, departments, or assignees."""
        result = gateway_client().execute_tool(
            tool_code="analytics.summary",
            actor={
                "user_id": user_id,
                "username": username,
                "roles": roles,
                "channel": "mcp",
                "source": "mcp-client",
            },
            payload={"summary_type": summary_type},
            session_id=session_id,
        )
        return result

    return mcp
