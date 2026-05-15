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
        "input_schemas": {
            "status": {
                "description": "Filter by work order status",
                "enum": ["new", "accepted", "in_progress", "on_hold", "resolved", "closed", "cancelled"],
            },
            "limit": {
                "description": "Maximum number of results to return",
                "type": "integer",
            },
        },
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
        "input_schemas": {
            "priority": {
                "description": "Priority level for the work order",
                "enum": ["low", "medium", "high", "critical"],
            },
        },
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
        "input_schemas": {
            "target_status": {
                "description": "The target status to transition to. Must be an allowed next status per workflow rules.",
                "enum": ["new", "accepted", "in_progress", "on_hold", "resolved", "closed", "cancelled"],
            },
        },
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
        "id": "workorders.confirm_closure",
        "title": "Confirm work order closure",
        "domain": "workorders",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Confirm the closure of a resolved work order.",
        "inputs": [
            "workorder_id",
        ],
        "outputs": [
            "workorder",
        ],
        "requires_confirmation": True,
        "required_role_scope": "confirm_closure",
    },
    {
        "id": "workorders.rate",
        "title": "Rate work order",
        "domain": "workorders",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Rate a closed work order.",
        "inputs": [
            "workorder_id",
            "rating",
        ],
        "outputs": [
            "workorder",
        ],
        "requires_confirmation": False,
        "required_role_scope": "rate",
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
    {
        "id": "inventory.devices.create",
        "title": "Create device",
        "domain": "inventory",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Create a new medical device in the inventory.",
        "inputs": [
            "name",
            "department_id",
            "model",
            "serial_number",
        ],
        "outputs": [
            "device",
        ],
        "requires_confirmation": True,
        "required_role_scope": "manage",
    },
    {
        "id": "inventory.devices.update",
        "title": "Update device",
        "domain": "inventory",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Update an existing medical device.",
        "inputs": [
            "device_id",
            "name",
            "department_id",
            "model",
            "serial_number",
        ],
        "outputs": [
            "device",
        ],
        "requires_confirmation": True,
        "required_role_scope": "manage",
    },
    {
        "id": "inventory.devices.archive",
        "title": "Archive device",
        "domain": "inventory",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Archive a medical device so it can no longer be assigned.",
        "inputs": [
            "device_id",
        ],
        "outputs": [
            "device",
        ],
        "requires_confirmation": True,
        "required_role_scope": "manage",
    },
    {
        "id": "analytics.summary",
        "title": "Analytics summary",
        "domain": "analytics",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Return read-only analytics summaries for status, departments, or assignees.",
        "inputs": [
            "summary_type",
        ],
        "outputs": [
            "summary",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "access.update_role_permissions",
        "title": "Update role permissions",
        "domain": "access",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Update permissions for a specific role in the role rules configuration.",
        "inputs": [
            "role_name",
            "permissions_map",
        ],
        "outputs": [
            "ok",
            "message",
        ],
        "requires_confirmation": True,
        "required_role_scope": "superuser",
    },
    {
        "id": "access.get_role_rules",
        "title": "Get role rules",
        "domain": "access",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Return the current role configuration from role_rules.json.",
        "inputs": [],
        "outputs": [
            "rules",
        ],
        "required_role_scope": "visible",
    },
    {
        "id": "access.users.list",
        "title": "List users",
        "domain": "access",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Return users with their roles and departments. Administrators only.",
        "inputs": [
            "query",
        ],
        "outputs": [
            "items",
        ],
        "required_role_scope": "superuser",
    },
    {
        "id": "access.users.update",
        "title": "Update user",
        "domain": "access",
        "mode": "write",
        "execution_mode": "service_layer",
        "description": "Update user details such as active status, department, and groups. Administrators only.",
        "inputs": [
            "user_id",
            "is_active",
            "department_id",
            "group_names",
        ],
        "outputs": [
            "user",
        ],
        "requires_confirmation": True,
        "required_role_scope": "superuser",
    },
    {
        "id": "access.groups.list",
        "title": "List groups",
        "domain": "access",
        "mode": "read",
        "execution_mode": "service_or_read_only_query",
        "description": "Return all available Django groups. Administrators only.",
        "inputs": [],
        "outputs": [
            "items",
        ],
        "required_role_scope": "superuser",
    },
]


def get_tool_registry():
    return {tool["id"]: tool for tool in TOOLS}


def get_registry_payload():
    return {**TOOL_REGISTRY_ROOT, "tools": TOOLS}
