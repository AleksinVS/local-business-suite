from __future__ import annotations

from django.conf import settings
from django.urls import reverse
from django.utils.timezone import localtime

from apps.ai.chat_settings import CHAT_SURFACE_FULL_PAGE, CHAT_SURFACE_SIDEBAR, get_recent_message_limit
from apps.ai.config_documents import get_ai_document_payloads
from apps.ai.commands import get_predefined_commands
from apps.ai.models import ChatMessage, ChatRun, ChatSession, SlashCommand
from apps.ai.services import (
    CHAT_ATTACHMENT_MAX_COUNT,
    CHAT_ATTACHMENT_MAX_SIZE,
    CHAT_ATTACHMENT_MIME_TYPES,
    get_or_create_sidebar_session,
)
from services.agent_runtime.protocols.common import AI_CHAT_UNAVAILABLE_MESSAGE

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
    "error": AI_CHAT_UNAVAILABLE_MESSAGE,
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
        "attachments": _serialize_attachments(message),
    }


def _serialize_attachments(message: ChatMessage) -> list[dict[str, object]]:
    """Expose only browser-safe attachment metadata, never storage internals."""
    result = []
    for attachment in message.attachments.all():
        url = ""
        try:
            url = str(attachment.file.url or "")
        except (AttributeError, ValueError):
            pass
        result.append({
            "id": str(attachment.id),
            "name": str(attachment.file_name or "attachment"),
            "size": int(attachment.file_size or 0),
            "type": str(attachment.file_type or ""),
            "url": url,
        })
    return result


def _serialize_full_page_message(message: ChatMessage) -> dict[str, object]:
    payload = _serialize_sidebar_message(message)
    payload["created_at_display"] = localtime(message.created_at).strftime("%H:%M")
    return payload


def _recoverable_prepared_run(session: ChatSession) -> dict[str, object] | None:
    """Return the oldest orphan prepared turn, never an already-running turn."""
    run = (
        ChatRun.objects.filter(session=session, status=ChatRun.Status.PREPARED)
        .select_related("user_message")
        .order_by("prepared_at", "id")
        .first()
    )
    if not run or not run.user_message_id:
        return None
    return {
        "status": ChatRun.Status.PREPARED,
        "run_id": run.run_id,
        "message_id": run.user_message_id,
        "assistant_message_id": run.assistant_message_id,
    }


def _command_catalog(user) -> dict[str, list[dict[str, object]]]:
    predefined = []
    for command in get_predefined_commands():
        predefined.append({
            "name": str(command.get("name") or ""),
            "aliases": list(command.get("aliases") or []),
            "description": str(command.get("description") or ""),
            "handler": str(command.get("handler") or ""),
            "requires_input": bool(command.get("requires_input")),
        })
    custom = [
        {
            "id": int(command["id"]),
            "name": str(command["name"] or ""),
            "shortcut": str(command["shortcut"] or ""),
            "description": str(command["description"] or ""),
        }
        for command in SlashCommand.objects.filter(user=user).values("id", "name", "shortcut", "description")
    ]
    return {"predefined": predefined, "custom": custom}


def _session_urls(session) -> dict[str, str]:
    return {
        "prepare_url": reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
        "run_url": reverse("ai:chat_run", kwargs={"external_id": session.external_id}),
        "model_url": reverse("ai:chat_update_model", kwargs={"external_id": session.external_id}),
        "title_url": reverse("ai:chat_update_title", kwargs={"external_id": session.external_id}),
        "delete_url": reverse("ai:chat_delete", kwargs={"external_id": session.external_id}),
        "new_url": reverse("ai:chat_index") + "?new=1",
        "hub_url": reverse("ai:hub"),
    }


def build_full_page_ai_ui_config(
    *, user, session: ChatSession, request=None, snapshot=None
) -> dict[str, object]:
    """Build the owned full-page config using the same native transport contract."""
    model_id = str((session.metadata or {}).get("model_id") or "")
    messages = list(
        session.messages.exclude(role=ChatMessage.Role.TOOL)
        .prefetch_related("attachments")
        .order_by("created_at", "id")
    )
    snapshot = get_ai_document_payloads(request=request, snapshot=snapshot)
    limit = get_recent_message_limit(
        CHAT_SURFACE_FULL_PAGE, request=request, snapshot=snapshot
    )
    messages = messages[-limit:]
    urls = _session_urls(session)
    return {
        "enabled": True,
        "driver": DRIVER_NATIVE,
        "surface": CHAT_SURFACE_FULL_PAGE,
        "thread_id": str(session.external_id),
        "session": {
            "id": str(session.external_id),
            "title": session.title or "Новый чат",
            "active": session.status == ChatSession.Status.ACTIVE,
            "channel": session.channel,
            "updated_at": localtime(session.updated_at).isoformat(),
        },
        "messages": [_serialize_full_page_message(message) for message in messages],
        "recoverable_run": _recoverable_prepared_run(session),
        "models": _model_options(model_id, request=request, snapshot=snapshot),
        "current_model_id": model_id,
        "commands": _command_catalog(user),
        "command_discovery": {"slash_prefix": "/", "server_authoritative": True},
        "attachment_policy": {
            "max_count": CHAT_ATTACHMENT_MAX_COUNT,
            "max_size": CHAT_ATTACHMENT_MAX_SIZE,
            "allowed_types": sorted(CHAT_ATTACHMENT_MIME_TYPES),
            "advisory": True,
        },
        "prepare_url": urls["prepare_url"],
        "runtime_url": urls["run_url"],
        "urls": urls,
        "protocol": {
            "agui_profile": getattr(settings, "LOCAL_BUSINESS_AI_UI_AGUI_PROFILE", "ag-ui@0.0.55"),
            "local_business_protocol": getattr(settings, "LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION", "1.0"),
        },
        "labels": DEFAULT_LABELS,
    }


def _sidebar_messages(session, *, request=None, snapshot=None) -> list[dict[str, object]]:
    recent_limit = get_recent_message_limit(
        CHAT_SURFACE_SIDEBAR, request=request, snapshot=snapshot
    )
    messages = list(
        session.messages.exclude(role=ChatMessage.Role.TOOL)
        .prefetch_related("attachments")
        .order_by("-created_at", "-id")[:recent_limit]
    )
    messages.reverse()
    return [_serialize_sidebar_message(message) for message in messages]


def _model_options(current_model_id: str, *, snapshot=None, request=None) -> list[dict[str, object]]:
    options = []
    snapshot = get_ai_document_payloads(request=request, snapshot=snapshot)
    for model in snapshot["ai.contract.models"]:
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
        "prepare_turn_url": reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}),
        "run_url": reverse("ai:chat_run", kwargs={"external_id": session.external_id}),
    }


def build_sidebar_ai_ui_config(
    *,
    user,
    driver: str | None = None,
    runtime_url: str = "",
    agent_id: str = "",
    request=None,
    snapshot=None,
) -> dict[str, object]:
    resolved_driver = driver or configured_ai_ui_driver()
    session = get_or_create_sidebar_session(user)
    model_id = (session.metadata or {}).get("model_id", "")
    if not runtime_url:
        if resolved_driver == DRIVER_COPILOTKIT:
            runtime_url = settings.LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL
        elif resolved_driver == DRIVER_NATIVE:
            runtime_url = reverse("ai:chat_run", kwargs={"external_id": session.external_id})
    if not agent_id:
        agent_id = settings.LOCAL_BUSINESS_COPILOTKIT_AGENT_ID

    snapshot = get_ai_document_payloads(request=request, snapshot=snapshot)
    config = {
        "enabled": True,
        "driver": resolved_driver,
        "runtime_url": runtime_url,
        "prepare_url": reverse("ai:chat_prepare_turn", kwargs={"external_id": session.external_id}) if resolved_driver == DRIVER_NATIVE else "",
        "agent_id": agent_id,
        "thread_id": str(session.external_id),
        "labels": DEFAULT_LABELS,
        "messages": _sidebar_messages(session, request=request, snapshot=snapshot),
        "recoverable_run": _recoverable_prepared_run(session),
        "models": _model_options(model_id, request=request, snapshot=snapshot),
        "current_model_id": model_id,
        "urls": _sidebar_urls(session),
        "protocol": {
            "agui_profile": getattr(settings, "LOCAL_BUSINESS_AI_UI_AGUI_PROFILE", "ag-ui@0.0.55"),
            "local_business_protocol": getattr(settings, "LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION", "1.0"),
        },
    }
    if resolved_driver == DRIVER_COPILOTKIT:
        config["forwarded_props"] = build_actor_payload(
            user=user,
            session=session,
            driver=resolved_driver,
            model_id=model_id,
        )
    return config
