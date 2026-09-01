from __future__ import annotations

from typing import Any

from .config_documents import get_ai_document_payloads


CHAT_SURFACE_FULL_PAGE = "full_page"
CHAT_SURFACE_SIDEBAR = "sidebar"


def get_chat_settings(
    surface: str = CHAT_SURFACE_FULL_PAGE,
    *,
    request=None,
    snapshot=None,
) -> dict[str, Any]:
    """Return effective settings from the request-local AI repository snapshot."""
    payload = get_ai_document_payloads(request=request, snapshot=snapshot).get(
        "ai.contract.chat_settings", {}
    )
    defaults = payload.get("defaults", {}) if isinstance(payload, dict) else {}
    surfaces = payload.get("surfaces", {}) if isinstance(payload, dict) else {}
    effective = dict(defaults)
    surface_config = surfaces.get(surface, {}) if isinstance(surfaces, dict) else {}
    if isinstance(surface_config, dict):
        effective.update(surface_config)
    effective["surface"] = surface
    return effective


def get_recent_message_limit(surface: str = CHAT_SURFACE_FULL_PAGE, *, request=None, snapshot=None) -> int:
    value = get_chat_settings(surface, request=request, snapshot=snapshot).get("recent_message_limit", 20)
    try:
        return min(max(int(value), 4), 50)
    except (TypeError, ValueError):
        return 20 if surface != CHAT_SURFACE_SIDEBAR else 8
