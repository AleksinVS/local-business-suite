from __future__ import annotations

import json

from django.conf import settings

from .ui_runtime.drivers import DRIVER_COPILOTKIT, DRIVER_NATIVE, authenticated_ai_ui_driver


def _request_page_context(request) -> dict[str, object]:
    resolver_match = getattr(request, "resolver_match", None)
    module = getattr(resolver_match, "namespace", "") or ""
    view_name = getattr(resolver_match, "url_name", "") or ""
    if ":" in module:
        module = module.split(":", 1)[0]
    return {
        "schema_version": "1",
        "page": {
            "module": module,
            "view": view_name,
        },
    }


def sidebar_ai_chat(request):
    user = getattr(request, "user", None)
    ai_ui_driver = authenticated_ai_ui_driver(user)
    is_authenticated = bool(getattr(user, "is_authenticated", False))
    copilotkit_enabled = is_authenticated and ai_ui_driver == DRIVER_COPILOTKIT
    native_ai_ui_enabled = is_authenticated and ai_ui_driver == DRIVER_NATIVE
    return {
        "show_sidebar_ai_chat": is_authenticated,
        "ai_ui_driver": ai_ui_driver,
        "copilotkit_enabled": copilotkit_enabled,
        "native_ai_ui_enabled": native_ai_ui_enabled,
        "copilotkit_runtime_url": settings.LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL,
        "copilotkit_agent_id": settings.LOCAL_BUSINESS_COPILOTKIT_AGENT_ID,
        "copilotkit_asset_version": "20260610-copilotkit-page",
        "native_ai_asset_version": "20260610-native-ag-ui-chat",
        "base_ai_context_json": json.dumps(_request_page_context(request), ensure_ascii=False),
    }
