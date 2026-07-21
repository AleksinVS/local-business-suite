from __future__ import annotations

import copy
from typing import Any

from django.conf import settings


CHAT_SURFACE_FULL_PAGE = "full_page"
CHAT_SURFACE_SIDEBAR = "sidebar"


def get_chat_settings(surface: str = CHAT_SURFACE_FULL_PAGE) -> dict[str, Any]:
    """Return effective chat settings for one UI surface."""
    payload = copy.deepcopy(getattr(settings, "LOCAL_BUSINESS_AI_CHAT_SETTINGS", {}) or {})
    defaults = payload.get("defaults", {}) if isinstance(payload, dict) else {}
    surfaces = payload.get("surfaces", {}) if isinstance(payload, dict) else {}
    effective = dict(defaults)
    surface_config = surfaces.get(surface, {}) if isinstance(surfaces, dict) else {}
    if isinstance(surface_config, dict):
        effective.update(surface_config)
    effective["surface"] = surface
    return effective


def get_recent_message_limit(surface: str = CHAT_SURFACE_FULL_PAGE) -> int:
    value = get_chat_settings(surface).get("recent_message_limit", 20)
    try:
        return min(max(int(value), 4), 50)
    except (TypeError, ValueError):
        return 20 if surface != CHAT_SURFACE_SIDEBAR else 8
