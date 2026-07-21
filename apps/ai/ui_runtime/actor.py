from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from django.conf import settings

from apps.ai.models import ChatSession

from .drivers import DRIVER_COPILOTKIT, DRIVER_NATIVE


COPILOTKIT_ACTOR_VERSION = "copilotkit-ag-ui-v1"
LOCAL_BUSINESS_AI_UI_ACTOR_VERSION = "local-business-ai-ui-v1"


def actor_version_for_driver(driver: str) -> str:
    if driver == DRIVER_COPILOTKIT:
        return COPILOTKIT_ACTOR_VERSION
    return LOCAL_BUSINESS_AI_UI_ACTOR_VERSION


def actor_source_for_driver(driver: str) -> str:
    if driver == DRIVER_COPILOTKIT:
        return "django-copilotkit"
    if driver == DRIVER_NATIVE:
        return "django-native-ai-ui"
    return "django-ai-ui"


def signature_payload(payload: dict[str, Any]) -> str:
    actor = payload.get("actor") or {}
    signed_payload = {
        "actor": {
            "actor_version": actor.get("actor_version", ""),
            "channel": actor.get("channel", ""),
            "is_superuser": bool(actor.get("is_superuser", False)),
            "origin_channel": actor.get("origin_channel", ""),
            "roles": list(actor.get("roles") or []),
            "source": actor.get("source", ""),
            "user_id": actor.get("user_id"),
            "username": actor.get("username", ""),
        },
        "actor_version": payload.get("actor_version", ""),
        "issued_at": payload.get("issued_at") or 0,
        "model_id": payload.get("model_id", ""),
        "origin_channel": payload.get("origin_channel", ""),
        "session_id": payload.get("session_id", ""),
        "ui_driver": payload.get("ui_driver", ""),
    }
    return json.dumps(signed_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sign_actor_payload(payload: dict[str, Any]) -> str:
    token = (settings.LOCAL_BUSINESS_AI_GATEWAY_TOKEN or "").encode("utf-8")
    message = signature_payload(payload).encode("utf-8")
    return hmac.new(token, message, hashlib.sha256).hexdigest()


def build_actor_payload(
    *,
    user,
    session: ChatSession,
    driver: str,
    model_id: str = "",
    page_context: dict[str, Any] | None = None,
    issued_at: int | None = None,
) -> dict[str, Any]:
    actor_version = actor_version_for_driver(driver)
    payload: dict[str, Any] = {
        "session_id": str(session.external_id),
        "model_id": model_id,
        "origin_channel": driver,
        "ui_driver": driver,
        "actor_version": actor_version,
        "issued_at": issued_at if issued_at is not None else int(time.time()),
        "actor": {
            "user_id": user.id,
            "username": user.username,
            "roles": list(user.groups.values_list("name", flat=True)),
            "is_superuser": user.is_superuser,
            "channel": ChatSession.Channel.SIDEBAR,
            "source": actor_source_for_driver(driver),
            "origin_channel": driver,
            "actor_version": actor_version,
        },
    }
    if page_context:
        payload["page_context"] = page_context
    payload["signature"] = sign_actor_payload(payload)
    return payload
