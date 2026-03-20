from .config import load_json, load_runtime_settings


def build_system_prompt() -> str:
    settings = load_runtime_settings()
    if settings.system_prompt_path:
        return settings.system_prompt_path.read_text(encoding="utf-8")

    tools_payload = load_json(settings.ai_tools_path)
    task_types_payload = load_json(settings.ai_task_types_path)

    tool_lines = [
        f"- {tool['id']}: {tool['description']} (mode={tool['mode']}, confirmation={tool.get('requires_confirmation', False)})"
        for tool in tools_payload["tools"]
    ]
    task_lines = [
        f"- {task['id']}: {task['description']}"
        for task in task_types_payload["task_types"]
    ]

    return "\n".join(
        [
            "You are the internal Local Business Suite operations agent.",
            "You work only through declared tools and must not invent side effects.",
            "You must respect role-based access and rely on tool responses for authorization.",
            "Before a write action, ask for confirmation unless the user already gave an explicit direct instruction.",
            "Prefer concise structured answers.",
            "Supported task types:",
            *task_lines,
            "Available tools:",
            *tool_lines,
        ]
    )
