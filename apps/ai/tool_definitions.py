TOOL_REGISTRY_ROOT = {
    "version": "1.0",
    "name": "chat_agent_tool_registry",
    "description": "Declared tools available to the chat and agent block.",
    "default_policies": {
        "authentication_required": True,
        "policy_enforced": True,
        "writes_require_confirmation": True,
        "direct_sql_writes_allowed": False,
    },
}

TOOLS = [
    {
        "id": "workorders.list",
        "title": "List work orders",
        "domain": "workorders",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Return work orders filtered by status and limit.",
        "inputs": [
            "status",
            "limit",
        ],
        "outputs": [
            "items",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "workorders.get",
        "title": "Get work order",
        "domain": "workorders",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Return a single work order by id or human-readable number.",
        "inputs": [
            "workorder_id",
            "number",
        ],
        "outputs": [
            "workorder",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "workorders.create",
        "title": "Create work order",
        "domain": "workorders",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Create a work order with department, subject (title), description, optional device, and priority.",
        "inputs": [
            "department_id",
            "subject",
            "description",
            "device_id",
            "priority",
        ],
        "outputs": [
            "workorder",
        ],
        "requires_confirmation": True,
        "required_role_scope": "create",
    },
    {
        "id": "workorders.transition",
        "title": "Transition work order",
        "domain": "workorders",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Move a work order to an allowed next status.",
        "inputs": [
            "workorder_id",
            "target_status",
        ],
        "outputs": [
            "workorder",
        ],
        "requires_confirmation": True,
        "required_role_scope": "transition",
    },
    {
        "id": "workorders.comment",
        "title": "Add work order comment",
        "domain": "workorders",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Append a comment to a work order timeline.",
        "inputs": [
            "workorder_id",
            "text",
        ],
        "outputs": [
            "comment",
        ],
        "requires_confirmation": False,
        "required_role_scope": "comment",
    },
    {
        "id": "departments.list",
        "title": "List departments",
        "domain": "core",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Return the hierarchical department tree or a filtered subset.",
        "inputs": [
            "query",
            "parent_id",
        ],
        "outputs": [
            "items",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "devices.list",
        "title": "List devices",
        "domain": "inventory",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Return devices for selection and lookup.",
        "inputs": [
            "query",
            "department_id",
            "archived",
        ],
        "outputs": [
            "items",
        ],
        "required_role_scope": "visible",
    },
]


def get_tool_registry():
    return {tool["id"]: tool for tool in TOOLS}


def get_registry_payload():
    return {**TOOL_REGISTRY_ROOT, "tools": TOOLS}