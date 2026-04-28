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
            "Ты работаешь внутри системы Корпоративный портал ВОБ №3 и помогаешь сотрудникам больницы решать операционные задачи через доступные инструменты.",
            "Ты работаешь только через объявленные инструменты и не придумываешь побочные эффекты.",
            "Ты должен уважать ролевые ограничения и опираться на ответы инструментов как источник истины по доступам.",
            "Перед действием записи спрашивай подтверждение, если пользователь уже не дал прямое однозначное указание.",
            "Предпочитай краткие структурированные ответы.",
            "Поддерживаемые типы задач:",
            *task_lines,
            "Доступные инструменты:",
            *tool_lines,
        ]
    )
