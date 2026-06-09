from __future__ import annotations

from django.conf import settings


DRIVER_LEGACY = "legacy"
DRIVER_COPILOTKIT = "copilotkit"
DRIVER_NATIVE = "native"
VALID_AI_UI_DRIVERS = {DRIVER_LEGACY, DRIVER_COPILOTKIT, DRIVER_NATIVE}


def normalize_ai_ui_driver(value: str | None) -> str:
    driver = (value or "").strip().lower()
    if driver in VALID_AI_UI_DRIVERS:
        return driver
    return DRIVER_LEGACY


def configured_ai_ui_driver() -> str:
    configured = getattr(settings, "LOCAL_BUSINESS_AI_UI_DRIVER", "")
    if configured and (
        configured != DRIVER_LEGACY
        or getattr(settings, "LOCAL_BUSINESS_AI_UI_DRIVER_EXPLICIT", False)
    ):
        return normalize_ai_ui_driver(configured)
    if getattr(settings, "LOCAL_BUSINESS_COPILOTKIT_ENABLED", False):
        return DRIVER_COPILOTKIT
    return DRIVER_LEGACY


def authenticated_ai_ui_driver(user) -> str:
    if not getattr(user, "is_authenticated", False):
        return DRIVER_LEGACY
    return configured_ai_ui_driver()


def is_copilotkit_driver(user) -> bool:
    return authenticated_ai_ui_driver(user) == DRIVER_COPILOTKIT


def is_native_driver(user) -> bool:
    return authenticated_ai_ui_driver(user) == DRIVER_NATIVE
