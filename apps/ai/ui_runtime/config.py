from __future__ import annotations

from django.conf import settings
from django.urls import reverse
from django.utils.timezone import localtime

from apps.ai.chat_settings import CHAT_SURFACE_SIDEBAR, get_recent_message_limit
from apps.ai.models import ChatMessage
from apps.ai.services import get_or_create_sidebar_session

from .actor import build_actor_payload
from .drivers import DRIVER_COPILOTKIT, DRIVER_NATIVE, configured_ai_ui_driver


DEFAULT_LABELS = {
    "title": "ИИ-чат",
    "initial": "Опишите задачу или попросите открыть объект в правой панели.",
    "placeholder": "Сообщение...",
    "new_chat": "Новый чат",
    "send": "Отправить",
    "assistant_typing": "Печатает...",
    "assistant": "Ассистент",
    "user": "Вы",
    "tool": "Инструмент",
    "tool_running": "Выполняется",
    "tool_done": "Готово",
    "error": "Не удалось получить ответ от ИИ-сервиса.",
    "clear_chat": "Очистить чат",
    "full_chat": "Открыть полный чат",
    "model": "Модель",
}


def _serialize_sidebar_message(message: ChatMessage) -> dict[str, object]:
    metadata = message.metadata or {}
    created_at = localtime(message.created_at)
    return {
        "id": str(message.id),
        "role": message.role,
        "content": message.content,
        "tool_name": message.tool_name,
        "created_at": created_at.isoformat(),
        "created_at_display": created_at.strftime("%H:%M"),
        "error": bool(metadata.get("error")),
    }


def _sidebar_messages(session) -> list[dict[str, object]]:
    recent_limit = get_recent_message_limit(CHAT_SURFACE_SIDEBAR)
    messages = list(session.messages.order_by("-created_at", "-id")[:recent_limit])
    messages.reverse()
    return [_serialize_sidebar_message(message) for message in messages]


def _model_options(current_model_id: str) -> list[dict[str, object]]:
    options = []
    for model in getattr(settings, "LOCAL_BUSINESS_AI_MODELS", []):
        model_id = str(model.get("id") or "")
        if not model_id:
            continue
        options.append(
            {
                "id": model_id,
                "name": str(model.get("name") or model_id),
                "default": bool(model.get("default")),
                "selected": model_id == current_model_id or (not current_model_id and bool(model.get("default"))),
            }
        )
    return options


def _sidebar_urls(session) -> dict[str, str]:
    return {
        "new_session_url": reverse("ai:ui_session_new"),
        "clear_session_url": reverse("ai:ui_session_clear"),
        "model_update_url": reverse("ai:chat_update_model", kwargs={"external_id": session.external_id}),
        "full_chat_url": reverse("ai:chat_detail", kwargs={"external_id": session.external_id}),
    }


def build_sidebar_ai_ui_config(
    *,
    user,
    driver: str | None = None,
    runtime_url: str = "",
    agent_id: str = "",
) -> dict[str, object]:
    resolved_driver = driver or configured_ai_ui_driver()
    session = get_or_create_sidebar_session(user)
    model_id = (session.metadata or {}).get("model_id", "")
    if not runtime_url:
        if resolved_driver == DRIVER_COPILOTKIT:
            runtime_url = settings.LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL
        elif resolved_driver == DRIVER_NATIVE:
            runtime_url = "/ai/ui/ag-ui/run/"
    if not agent_id:
        agent_id = settings.LOCAL_BUSINESS_COPILOTKIT_AGENT_ID

    actor_payload = build_actor_payload(
        user=user,
        session=session,
        driver=resolved_driver,
        model_id=model_id,
    )
    return {
        "enabled": True,
        "driver": resolved_driver,
        "runtime_url": runtime_url,
        "agent_id": agent_id,
        "thread_id": str(session.external_id),
        "forwarded_props": actor_payload,
        "labels": DEFAULT_LABELS,
        "messages": _sidebar_messages(session),
        "models": _model_options(model_id),
        "current_model_id": model_id,
        "urls": _sidebar_urls(session),
        "protocol": {
            "agui_profile": getattr(settings, "LOCAL_BUSINESS_AI_UI_AGUI_PROFILE", "ag-ui@0.0.55"),
            "local_business_protocol": getattr(settings, "LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION", "1.0"),
        },
    }
