from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from .ui_runtime.drivers import DRIVER_COPILOTKIT, DRIVER_NATIVE, authenticated_ai_ui_driver

# Fallback asset versions are used when статика под ``staticfiles/`` ещё
# не собрана (``manage.py collectstatic`` не запускался): runserver в DEBUG
# всё равно отдаёт исходники, поэтому пользователь увидит работающий чат.
# См. ADR-0029.
_NATIVE_JS_RELPATH = "src/ai_ui/native_ai.js"
_NATIVE_CSS_RELPATH = "src/ai_ui/native_ai.css"
_COPILOTKIT_JS_RELPATH = "dist/copilotkit/copilotkit-island.js"
_COPILOTKIT_CSS_RELPATH = "dist/copilotkit/copilotkit-island.css"

_NATIVE_FALLBACK_VERSION = "20260610-native-ag-ui-chat"
_COPILOTKIT_FALLBACK_VERSION = "20260610-copilotkit-page"


def _staticfiles_root() -> Path:
    """Возвращает путь к ``staticfiles/`` (или ``STATIC_ROOT`` из настроек)."""
    static_root = getattr(settings, "STATIC_ROOT", "")
    if static_root:
        return Path(static_root)
    return Path(settings.BASE_DIR) / "staticfiles"


def _file_asset_version(relpath: str, fallback: str) -> str:
    """sha256 от ``mtime+size`` файла под ``STATIC_ROOT``/``staticfiles``.

    Если файл отсутствует (``collectstatic`` ещё не запускался), возвращает
    fallback-строку — runtime в DEBUG всё равно отдаст исходник.
    """
    try:
        full_path = _staticfiles_root() / relpath
    except (OSError, ValueError):
        return fallback
    try:
        stat = full_path.stat()
    except FileNotFoundError:
        return fallback
    digest = hashlib.sha256(f"{relpath}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")).hexdigest()
    return digest[:12]


@lru_cache(maxsize=8)
def native_ai_asset_version() -> str:
    return _file_asset_version(_NATIVE_JS_RELPATH, _NATIVE_FALLBACK_VERSION)


@lru_cache(maxsize=8)
def native_ai_css_version() -> str:
    return _file_asset_version(_NATIVE_CSS_RELPATH, _NATIVE_FALLBACK_VERSION)


@lru_cache(maxsize=8)
def copilotkit_asset_version() -> str:
    js_version = _file_asset_version(_COPILOTKIT_JS_RELPATH, _COPILOTKIT_FALLBACK_VERSION)
    css_version = _file_asset_version(_COPILOTKIT_CSS_RELPATH, _COPILOTKIT_FALLBACK_VERSION)
    if js_version == _COPILOTKIT_FALLBACK_VERSION and css_version == _COPILOTKIT_FALLBACK_VERSION:
        return _COPILOTKIT_FALLBACK_VERSION
    combined = hashlib.sha256(f"{js_version}|{css_version}".encode("utf-8")).hexdigest()
    return combined[:12]


@lru_cache(maxsize=8)
def copilotkit_css_version() -> str:
    return _file_asset_version(_COPILOTKIT_CSS_RELPATH, _COPILOTKIT_FALLBACK_VERSION)


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
        "copilotkit_asset_version": copilotkit_asset_version(),
        "copilotkit_css_version": copilotkit_css_version(),
        "native_ai_asset_version": native_ai_asset_version(),
        "native_ai_css_version": native_ai_css_version(),
        "base_ai_context_json": json.dumps(_request_page_context(request), ensure_ascii=False),
    }
