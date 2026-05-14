"""
Predefined slash commands and resolution logic.

Predefined commands are declared here (like tool_definitions.py) and never
stored in the database.  Custom per-user commands live in the SlashCommand model.
"""

PREDEFINED_COMMANDS = [
    {
        "name": "навыки",
        "aliases": ["skills", "ski"],
        "description": "Показать возможности ассистента",
        "handler": "skills",
        "requires_input": False,
        "prompt_template": (
            "Кратко расскажи пользователю, какие задачи ты можешь решить. "
            "Описывай только то, что пользователь может попросить тебя сделать — "
            "обычными словами, без технических названий инструментов, id или кодов. "
            "Не упоминай внутренние механизмы (activate_skill, tool_code и т.п.). "
            "Сгруппируй по темам: заявки, справочники, медизделия, аналитика. "
            "Для каждой группы — 1–2 предложения с примерами запросов."
        ),
    },
    {
        "name": "команды",
        "aliases": ["commands", "cmd"],
        "description": "Управление командами: список, создание, удаление",
        "handler": "commands",
        "requires_input": False,
        "prompt_template": "",
    },
]


def get_predefined_commands():
    """Return the list of predefined command dicts."""
    return PREDEFINED_COMMANDS


def resolve_command(text):
    """Check if *text* starts with a predefined slash command.

    Returns ``(cmd_spec, remainder)`` if matched, ``(None, text)``
    otherwise.  *remainder* is whatever follows the command token.
    """
    text = text.strip()
    if not text.startswith("/"):
        return None, text

    parts = text[1:].split(None, 1)
    token = parts[0].lower()
    remainder = parts[1] if len(parts) > 1 else ""

    for cmd in PREDEFINED_COMMANDS:
        if token == cmd["name"] or token in cmd.get("aliases", []):
            return cmd, remainder

    return None, text


def resolve_custom_command(text, user_commands):
    """Check if *text* starts with a custom slash command.

    *user_commands* is a queryset or list of ``SlashCommand`` objects.

    Returns ``(slash_command_obj, remainder)`` if matched,
    ``(None, text)`` otherwise.
    """
    text = text.strip()
    if not text.startswith("/"):
        return None, text

    parts = text[1:].split(None, 1)
    token = parts[0].lower()
    remainder = parts[1] if len(parts) > 1 else ""

    for cmd in user_commands:
        if token == cmd.name.lower() or (
            cmd.shortcut and token == cmd.shortcut.lower()
        ):
            return cmd, remainder

    return None, text