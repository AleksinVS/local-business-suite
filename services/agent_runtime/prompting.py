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
            "- Для поиска используй `memory.search` с параметрами `query`, `limit`, `sensitivity`, `corpus`.",
            "- По умолчанию `corpus=\"knowledge\"` ищет по принятому знанию. Если пользователь явно просит искать в исходных файлах, документах или их содержимом, вызывай `memory.search` с `corpus=\"source_data\"`.",
            "- Единственный профиль ранжирования (гибрид полнотекстового и векторного поиска, слияние RRF) применяется всегда на сервере; выбор режима поиска, профиля ранжирования или сырых весов каналов недоступен — не передавай такие параметры.",
            "- Для просьбы пользователя \"запомни\" используй `memory.remember`; инструмент синхронно пишет файл знания, делает git commit и индексирует его за один вызов — очереди/статуса опроса нет.",
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


def _build_ui_context_section() -> str:
    return "\n".join(
        [
            "",
            "## Текущий контекст окна:",
            "- У тебя есть инструмент управления интерфейсом `ui.open_right_panel`; не отвечай, что у тебя нет доступа к открытию правого сайдбара, пока не попробуешь этот инструмент.",
            "- Модульные сценарии открытия объектов описаны в skills. Если пользователь просит открыть заявку, запись листа ожидания или объект модуля, сначала выбери подходящий skill из каталога и активируй его.",
            "- Если пользователь говорит `эта карточка`, `текущая запись`, `текущий документ`, `этот issue`, `здесь` или задает вопрос, зависящий от открытой страницы, сначала вызови `ui.get_current_context`.",
            "- Контекст окна возвращает только безопасную серверно проверенную сводку; не считай клиентский display фактом.",
            "- Если пользователь просит открыть или показать объект в интерфейсе, вызови `ui.open_right_panel` с `source_code`, `object_type`, `object_id` и `mode=\"view\"`.",
            "- Если пользователь просит открыть `эту карточку` или `текущую запись`, и из диалога не ясно, какой это объект, сначала вызови `ui.get_current_context`, затем используй его selection для `ui.open_right_panel`.",
            "- `ui.open_right_panel` меняет только состояние интерфейса: не используй его для редактирования, создания, смены статуса или комментариев.",
            "- Если `ui.get_current_context` вернул `context_stale` или `context_unavailable`, попроси пользователя заново открыть объект или уточнить идентификатор.",
            "- Для действий записи текущий контекст может подставить объект, но не отменяет confirmation flow.",
            "- Если вопрос не зависит от открытого окна, не вызывай `ui.get_current_context` без необходимости.",
        ]
    )


def build_system_prompt(skills_catalog: list = None, active_skill_content: str = "") -> str:
    settings = load_runtime_settings()

    # Skills sections
    catalog_text = ""
    if skills_catalog:
        catalog_text = "\n## Доступные навыки (Skills):\n"
        for s in skills_catalog:
            examples = s.get("trigger_examples") or []
            examples_text = f"; примеры: {', '.join(examples[:3])}" if examples else ""
            catalog_text += f"- **{s.get('name')}**: {s.get('description')} (id: {s.get('id')}{examples_text})\n"
        catalog_text += "\nЕсли задача требует специального навыка, сначала вызови `activate_skill(skill_id='id')`, затем следуй загруженным инструкциям.\n"

    active_skill_text = ""
    if active_skill_content:
        active_skill_text = f"\n## ТЕКУЩИЙ АКТИВНЫЙ НАВЫК:\n{active_skill_content}\n"

    alias_section = _build_alias_section()
    memory_section = _build_memory_section()
    ui_context_section = _build_ui_context_section()

    if settings.system_prompt_path:
        base_prompt = settings.system_prompt_path.read_text(encoding="utf-8")
        return f"{base_prompt}\n{alias_section}\n{memory_section}\n{ui_context_section}\n{catalog_text}{active_skill_text}"

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
            ui_context_section,
        ]
    )
