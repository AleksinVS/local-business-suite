from .config import load_json, load_runtime_settings
from .task_types import STATUS_ALIASES, PRIORITY_ALIASES, STATUS_TRANSITIONS


def _build_alias_section() -> str:
    """Generate a Russian-language status/priority/transition mapping section
    for the system prompt, derived from the canonical alias data in task_types."""
    lines = [
        "",
        "## Статусы заявок (внутренние ключи для параметров инструментов):",
    ]
    for key, aliases in STATUS_ALIASES.items():
        label = aliases[0]
        lines.append(f"- {key} → {label}")
    lines.append("")
    lines.append("## Приоритеты заявок (внутренние ключи для параметров инструментов):")
    for key, aliases in PRIORITY_ALIASES.items():
        label = aliases[0]
        lines.append(f"- {key} → {label}")
    lines.append("")
    lines.append("## Допустимые переходы статусов:")
    for from_status, to_statuses in STATUS_TRANSITIONS.items():
        targets = ", ".join(to_statuses) if to_statuses else "(нет)"
        lines.append(f"- {from_status} → {targets}")
    lines.append("")
    lines.append(
        "Всегда используй внутренние ключи (латинские, с подчёркиваниями: "
        "new, in_progress, on_hold и т.д.) в параметрах инструментов "
        "status, target_status и priority. "
        "Если пользователь говорит по-русски, сопоставляй русские названия "
        "с внутренними ключами."
    )
    return "\n".join(lines)


def _build_memory_section() -> str:
    return "\n".join(
        [
            "",
            "## Система памяти (Memory Service):",
            "- Для поиска используй `memory.search`.",
            "- Для просьбы пользователя \"запомни\" используй `memory.remember`; инструмент ставит задачу записи в очередь и возвращает статус, а не записывает знание синхронно.",
            "- По умолчанию `memory.remember` пишет в персональную память пользователя. В организационную память пиши только при явной просьбе \"для всех\" или \"для организации\"; права проверит Django.",
            "- Для исправления или удаления персональной памяти используй `memory.update_personal`. Если `memory_id` неизвестен, сначала найди нужное знание через `memory.search` и уточни у пользователя, что менять.",
            "- Используй `memory.search`, когда пользователь просит найти сведения в памяти, безопасном корпусе знаний, прошлых контекстах, индексах, citations или спрашивает, что известно по объекту/заявке/оборудованию.",
            "- Память хранится и проверяется на стороне Django: файлы знаний, метаданные, индексы, graph facts, index jobs, access audit и eval cases.",
            "- Индексы строятся только по safe corpus после privacy pipeline; raw paths, секреты и original PII нельзя раскрывать пользователю.",
            "- Если пользователь просит сохранить пароль, токен или другой секрет, не повторяй и не раскрывай значение секрета. `memory.remember` должен сохранить только безопасный `<SECRET_HANDLE:...>` и несекретный контекст; значение секрета остается во внешнем хранилище.",
            "- Успешный ответ из памяти должен опираться на citations: source_code, source_object_id, knowledge_id, fact_id, snapshot_hash, text_hash, sensitivity.",
            "- Если `memory.search` вернул пустые items, объясни, что подходящий контекст не найден или недоступен по scope пользователя; не выдумывай содержимое памяти.",
            "- Если пользователь спрашивает, как проверить память, предложи: `python manage.py validate_architecture_contracts`, `python manage.py memory_eval --dry-run`, проверку Django Admin и `MemoryAccessAudit`.",
            "- Если пользователь спрашивает про развертывание памяти, ссылайся на `docs/deployment/MEMORY_DEPLOYMENT.md`; для пользовательских сценариев — на `docs/guides/MEMORY_USER_GUIDE.md`.",
            "- Текущая архитектура: memory service не является отдельным сетевым сервисом; это Django app `apps.memory` плюс tool gateway для `memory.search`, `memory.remember` и `memory.update_personal`. Agent runtime и другие сервисы должны обращаться к памяти через Django gateway/API, а не напрямую к файлам или индексам.",
        ]
    )


def build_system_prompt(skills_catalog: list = None, active_skill_content: str = "") -> str:
    settings = load_runtime_settings()

    # Skills sections
    catalog_text = ""
    if skills_catalog:
        catalog_text = "\n## Доступные навыки (Skills):\n"
        for s in skills_catalog:
            catalog_text += f"- **{s.get('name')}**: {s.get('description')} (id: {s.get('id')})\n"
        catalog_text += "\nЕсли задача требует специального навыка, используй `activate_skill(skill_id='id')`.\n"

    active_skill_text = ""
    if active_skill_content:
        active_skill_text = f"\n## ТЕКУЩИЙ АКТИВНЫЙ НАВЫК:\n{active_skill_content}\n"

    alias_section = _build_alias_section()
    memory_section = _build_memory_section()

    if settings.system_prompt_path:
        base_prompt = settings.system_prompt_path.read_text(encoding="utf-8")
        return f"{base_prompt}\n{alias_section}\n{memory_section}\n{catalog_text}{active_skill_text}"

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
            catalog_text,
            active_skill_text,
            "Ты работаешь только через объявленные инструменты и не придумываешь побочные эффекты.",
            "Ты должен уважать ролевые ограничения и опираться на ответы инструментов как источник истины по доступам.",
            "Перед действием записи спрашивай подтверждение, если пользователь уже не дал прямое однозначное указание.",
            "Предпочитай краткие структурированные ответы.",
            "Поддерживаемые типы задач:",
            *task_lines,
            "Доступные инструменты:",
            *tool_lines,
            alias_section,
            memory_section,
        ]
    )
