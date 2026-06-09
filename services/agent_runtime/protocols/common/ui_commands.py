from typing import Any


OPEN_RIGHT_PANEL_VERSION = "1.0"


def normalize_open_right_panel_command(command: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(command, dict):
        return None
    if command.get("type") != "open_right_panel":
        return None
    htmx_url = str(command.get("htmx_url") or command.get("url") or "")
    if not htmx_url.startswith("/") or htmx_url.startswith("//"):
        return None
    return {
        "type": "open_right_panel",
        "version": str(command.get("version") or OPEN_RIGHT_PANEL_VERSION),
        "source_code": command.get("source_code", ""),
        "object_type": command.get("object_type", ""),
        "object_id": str(command.get("object_id", "")),
        "mode": command.get("mode", "view"),
        "title": command.get("title", "Загрузка..."),
        "htmx_url": htmx_url,
        "target": "#global-right-panel-content",
        "swap": command.get("swap", "innerHTML"),
        "drawer_size": command.get("drawer_size", "default"),
    }


def normalize_ui_commands(ui_commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_commands = []
    for command in ui_commands:
        normalized = normalize_open_right_panel_command(command)
        if normalized:
            safe_commands.append(normalized)
    return safe_commands
