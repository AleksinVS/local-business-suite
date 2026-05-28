from __future__ import annotations

import json


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
    return {
        "show_sidebar_ai_chat": bool(getattr(user, "is_authenticated", False)),
        "base_ai_context_json": json.dumps(_request_page_context(request), ensure_ascii=False),
    }
