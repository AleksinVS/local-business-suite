from typing import Any


OPEN_RIGHT_PANEL_VERSION = "1.0"
MAX_UI_COMMANDS = 8
MAX_FIELD_LENGTH = 240
ALLOWED_OPEN_RIGHT_PANEL_MODES = {"view", "edit", "create"}
ALLOWED_OPEN_RIGHT_PANEL_SWAPS = {"innerHTML"}


def _safe_string(value: Any, *, max_length: int = MAX_FIELD_LENGTH) -> str:
    return str(value or "").replace("\x00", "").strip()[:max_length]


def normalize_open_right_panel_command(command: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(command, dict):
        return None
    if command.get("type") != "open_right_panel":
        return None
    htmx_url = _safe_string(command.get("htmx_url") or command.get("url"), max_length=500)
    if not htmx_url.startswith("/") or htmx_url.startswith("//"):
        return None
    mode = _safe_string(command.get("mode") or "view", max_length=32)
    if mode not in ALLOWED_OPEN_RIGHT_PANEL_MODES:
        mode = "view"
    swap = _safe_string(command.get("swap") or "innerHTML", max_length=32)
    if swap not in ALLOWED_OPEN_RIGHT_PANEL_SWAPS:
        swap = "innerHTML"
    return {
        "type": "open_right_panel",
        "version": _safe_string(command.get("version") or OPEN_RIGHT_PANEL_VERSION, max_length=16),
        "source_code": _safe_string(command.get("source_code"), max_length=80),
        "object_type": _safe_string(command.get("object_type"), max_length=80),
        "object_id": _safe_string(command.get("object_id"), max_length=80),
        "mode": mode,
        "title": _safe_string(command.get("title") or "Загрузка...", max_length=160),
        "htmx_url": htmx_url,
        "target": "#global-right-panel-content",
        "swap": swap,
        "drawer_size": _safe_string(command.get("drawer_size") or "default", max_length=40),
    }


def normalize_ui_commands(ui_commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_commands = []
    for command in ui_commands[:MAX_UI_COMMANDS]:
        normalized = normalize_open_right_panel_command(command)
        if normalized:
            safe_commands.append(normalized)
    return safe_commands
