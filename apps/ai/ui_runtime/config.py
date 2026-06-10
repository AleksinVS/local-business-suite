from __future__ import annotations

from django.conf import settings

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
        "protocol": {
            "agui_profile": getattr(settings, "LOCAL_BUSINESS_AI_UI_AGUI_PROFILE", "ag-ui@0.0.55"),
            "local_business_protocol": getattr(settings, "LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION", "1.0"),
        },
    }
