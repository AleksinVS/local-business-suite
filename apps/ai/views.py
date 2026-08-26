import json
import uuid
import logging
import hmac
import hashlib
import time
import re
from django.db import IntegrityError, transaction

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.http import HttpResponseForbidden, JsonResponse, StreamingHttpResponse
from django.views import View
from django.views.generic import DetailView, RedirectView, TemplateView
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from services.agent_runtime.protocols.common import AI_CHAT_UNAVAILABLE_MESSAGE

from .commands import get_predefined_commands, resolve_command, resolve_custom_command
from .models import AgentActionLog, ChatMessage, ChatRun, ChatSession, ChatAttachment, SlashCommand
from .chat_settings import CHAT_SURFACE_FULL_PAGE, CHAT_SURFACE_SIDEBAR, get_chat_settings
from .page_context import (
    bind_page_context_to_message,
    build_runtime_page_context,
    sanitize_page_context_envelope,
    update_window_context_snapshot,
)
from .runtime_client import AgentRuntimeClient, AgentRuntimeError
from .services import (
    append_chat_message,
    archive_chat_session,
    CHAT_ATTACHMENT_MAX_COUNT,
    clear_sidebar_session,
    create_new_sidebar_session,
    generate_session_title,
    get_or_create_sidebar_session,
    normalize_session_external_id,
    serialize_session_history,
    validate_chat_attachment,
)
from .tooling import UnknownToolError, execute_pending_action, execute_tool
from .ui_runtime.actor import build_actor_payload, sign_actor_payload, signature_payload
from .ui_runtime.config import build_full_page_ai_ui_config, build_sidebar_ai_ui_config
from .ui_runtime.drivers import DRIVER_COPILOTKIT, DRIVER_NATIVE, configured_ai_ui_driver

logger = logging.getLogger(__name__)

PAGE_CONTEXT_RATE_LIMIT_PER_MINUTE = 120
CHAT_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CHAT_PARTIAL_CONTENT_MAX_LENGTH = 4096
CHAT_RUN_MAX_EVENTS = 512
CHAT_RUN_MAX_EVENT_BYTES = 512 * 1024

_AGUI_PROXY_EVENT_TYPES = {
    "RUN_STARTED",
    "RUN_FINISHED",
    "RUN_ERROR",
    "TEXT_MESSAGE_START",
    "TEXT_MESSAGE_CONTENT",
    "TEXT_MESSAGE_END",
    "TOOL_CALL_START",
    "TOOL_CALL_ARGS",
    "TOOL_CALL_END",
    "TOOL_CALL_RESULT",
    "STATE_SNAPSHOT",
    "STATE_DELTA",
    "CUSTOM",
}


def classify_chat_runtime_error(exc):
    exc_name = exc.__class__.__name__
    cause = getattr(exc, "__cause__", None)
    cause_name = cause.__class__.__name__ if cause else ""
    combined = f"{exc_name} {cause_name} {exc}".lower()

    if "timeout" in combined or "timed out" in combined:
        return "agent_runtime_timeout", "превышено время ожидания"
    if "connect" in combined or "connection" in combined or "network" in combined:
        return "agent_runtime_unavailable", "ИИ-сервис недоступен"
    if "status" in combined or "http" in combined:
        return "agent_runtime_http_error", "ИИ-сервис вернул ошибку"
    if isinstance(exc, AgentRuntimeError):
        return "agent_runtime_error", "ИИ-сервис вернул ошибку"
    return "agent_runtime_error", "внутренняя ошибка обработки чата"


def allow_page_context_update(user_id) -> bool:
    bucket = int(time.time() // 60)
    cache_key = f"ai:page-context-rate:{user_id}:{bucket}"
    cache.add(cache_key, 0, timeout=90)
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=90)
        count = 1
    return count <= PAGE_CONTEXT_RATE_LIMIT_PER_MINUTE


def build_chat_error_payload(*, exc, request_id, conversation_id, technical_trace_id=None):
    error_code, _reason = classify_chat_runtime_error(exc)
    payload = {
        "error": True,
        "error_code": error_code,
        "message": AI_CHAT_UNAVAILABLE_MESSAGE,
        "request_id": request_id,
        "conversation_id": conversation_id,
    }
    if technical_trace_id:
        payload["technical_trace_id"] = technical_trace_id
    return payload


def record_chat_runtime_error(
    *,
    session,
    actor,
    user_message,
    exc,
    conversation_id,
    request_id,
    origin_channel,
    model_id,
    runtime_method,
    partial_content="",
):
    prompt = user_message.content if user_message else ""
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else ""
    error_code, reason = classify_chat_runtime_error(exc)
    action = AgentActionLog.objects.create(
        session=session,
        message=user_message,
        actor=actor,
        tool_code=f"agent_runtime.{runtime_method}",
        action_kind=AgentActionLog.ActionKind.READ,
        status=AgentActionLog.Status.FAILED,
        request_payload={
            "conversation_id": conversation_id,
            "request_id": request_id,
            "origin_channel": origin_channel,
            "model_id": model_id,
            "session_external_id": str(session.external_id),
            "prompt_sha256": prompt_hash,
            "prompt_length": len(prompt),
        },
        response_payload={
            "error_code": error_code,
            "reason": reason,
            "error_type": exc.__class__.__name__,
            "partial_content_length": len(partial_content),
            "has_partial_content": bool(partial_content),
        },
        error_message=str(exc)[:4000],
    )
    payload = build_chat_error_payload(
        exc=exc,
        request_id=request_id,
        conversation_id=conversation_id,
        technical_trace_id=action.id,
    )
    assistant = append_chat_message(
        session=session,
        role=ChatMessage.Role.ASSISTANT,
        content=payload["message"],
        metadata={
            "error": True,
            "error_code": error_code,
            "conversation_id": conversation_id,
            "request_id": request_id,
            "technical_trace_id": action.id,
            "runtime_method": runtime_method,
            "streamed": runtime_method == "ag_ui",
            "partial": bool(partial_content),
        },
    )
    request_ids = list(session.metadata.get("request_ids", []))
    if request_id not in request_ids:
        request_ids.append(request_id)
    session.metadata = {
        **session.metadata,
        "conversation_id": conversation_id,
        "request_ids": request_ids,
        "last_error_request_id": request_id,
        "last_error_action_id": action.id,
        "last_error_code": error_code,
    }
    session.save(update_fields=["metadata", "updated_at"])
    payload["assistant_message_id"] = assistant.id
    return payload


def gateway_token_is_valid(request):
    expected_token = settings.LOCAL_BUSINESS_AI_GATEWAY_TOKEN or ""
    gateway_token = request.headers.get("X-AI-Gateway-Token", "")
    return bool(expected_token) and hmac.compare_digest(gateway_token, expected_token)


def copilotkit_signature_payload(payload):
    return signature_payload(payload)


def sign_copilotkit_actor_payload(payload):
    return sign_actor_payload(payload)


def reject_invalid_gateway_token(request):
    if not gateway_token_is_valid(request):
        return HttpResponseForbidden("Токен шлюза ИИ недействителен.")
    return None


def validate_gateway_actor(actor_context, session_id=None):
    if not isinstance(actor_context, dict):
        return JsonResponse({"error": "Контекст исполнителя должен быть JSON-объектом."}, status=400)

    actor_user_id = actor_context.get("user_id")
    if not actor_user_id:
        return JsonResponse({"error": "Контекст исполнителя должен содержать user_id."}, status=403)
    try:
        actor_user_id = int(actor_user_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Контекст исполнителя содержит некорректный user_id."}, status=403)
    if actor_user_id <= 0:
        return JsonResponse({"error": "Контекст исполнителя содержит некорректный user_id."}, status=403)

    User = get_user_model()
    actor = User.objects.filter(pk=actor_user_id, is_active=True).first()
    if not actor:
        return JsonResponse({"error": "Исполнитель не найден или отключен."}, status=403)

    actor_username = actor_context.get("username")
    if actor_username and actor_username != actor.username:
        logger.warning(
            "Denied AI gateway username mismatch: actor_user=%s supplied_username=%s",
            actor_user_id,
            actor_username,
        )
        return JsonResponse({"error": "Имя исполнителя не совпадает с user_id."}, status=403)

    if not session_id:
        return None
    session_external_id = normalize_session_external_id(session_id)
    session = ChatSession.objects.filter(external_id=session_external_id).first()
    if not session:
        return None
    if str(actor_user_id) != str(session.user_id):
        logger.warning(
            "Denied AI gateway actor mismatch: session=%s session_user=%s actor_user=%s",
            session.external_id,
            session.user_id,
            actor_user_id,
        )
        return JsonResponse({"error": "Исполнитель не совпадает с владельцем сессии."}, status=403)
    return None


def context_trace_metadata(user_msg):
    runtime_context = build_runtime_page_context(user_msg)
    digest = runtime_context.get("digest") or {}
    return {
        "page_context_present": runtime_context.get("page_context_present", False),
        "page_context_status": runtime_context.get("page_context_status", ""),
        "context_snapshot_id": runtime_context.get("context_snapshot_id"),
        "window_id": runtime_context.get("window_id", ""),
        "context_version": runtime_context.get("context_version") or 0,
        "context_hash": runtime_context.get("context_hash", ""),
        "context_hint": runtime_context.get("context_hint", ""),
        "module": digest.get("module", ""),
        "object_type": digest.get("object_type", ""),
        "object_id_hash": digest.get("object_id_hash", ""),
    }


def agui_messages_from_history(history):
    messages = []
    for index, message in enumerate(history):
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        messages.append(
            {
                "id": f"history_{index}",
                "role": role,
                "content": str(message.get("content") or ""),
                "name": str(message.get("tool_name") or ""),
            }
        )
    return messages


def parse_agui_sse_events(buffer, chunk):
    combined = (buffer or "") + (chunk or "")
    combined = combined.replace("\r\n", "\n")
    blocks = combined.split("\n\n")
    remainder = blocks.pop() or ""
    events = []
    for block in blocks:
        data_lines = []
        for line in block.split("\n"):
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events, remainder


def collect_agui_event(event, collector):
    event_type = event.get("type")
    if event_type == "TEXT_MESSAGE_CONTENT":
        collector["content"].append(str(event.get("delta") or ""))
        return
    if event_type == "RUN_ERROR":
        collector["error"] = {
            "message": AI_CHAT_UNAVAILABLE_MESSAGE,
            "code": str(event.get("code") or "agent_runtime_error"),
        }
        return
    if event_type == "TOOL_CALL_START":
        tool_call_id = str(event.get("toolCallId") or f"tool_{len(collector['tool_trace']) + 1}")
        collector["tools_by_id"][tool_call_id] = {
            "tool_call_id": tool_call_id,
            "tool": str(event.get("toolCallName") or "tool"),
            "status": "started",
        }
        collector["tool_trace"].append(collector["tools_by_id"][tool_call_id])
        return
    if event_type == "TOOL_CALL_ARGS":
        tool_call_id = str(event.get("toolCallId") or "")
        trace = collector["tools_by_id"].get(tool_call_id)
        if trace:
            trace["status"] = "args_received"
        return
    if event_type == "TOOL_CALL_END":
        tool_call_id = str(event.get("toolCallId") or "")
        trace = collector["tools_by_id"].get(tool_call_id)
        if trace:
            trace["status"] = "completed"
        return
    if event_type == "TOOL_CALL_RESULT":
        tool_call_id = str(event.get("toolCallId") or "")
        trace = collector["tools_by_id"].get(tool_call_id)
        if trace:
            trace["status"] = "result_received"
        return
    if event_type == "STATE_DELTA":
        for operation in event.get("delta") if isinstance(event.get("delta"), list) else []:
            if not isinstance(operation, dict):
                continue
            if operation.get("path") not in {"/localBusiness/uiCommands", "/localBusinessUiCommands"}:
                continue
            value = operation.get("value")
            if isinstance(value, list):
                collector["ui_commands"].extend(item for item in value if isinstance(item, dict))
        return
    if event_type == "CUSTOM" and event.get("name") == "local_business.ui_command":
        value = event.get("value")
        if isinstance(value, dict):
            collector["ui_commands"].append(value)


def _validate_chat_run_id(value):
    run_id = str(value or "").strip()
    if not CHAT_RUN_ID_RE.fullmatch(run_id):
        raise ValidationError("Некорректный идентификатор запуска.")
    return run_id


def _chat_run_payload(run):
    return {
        "status": run.status,
        "run_id": run.run_id,
        "message_id": run.user_message_id,
        "assistant_message_id": run.assistant_message_id,
        "session_id": str(run.session.external_id),
    }


def _chat_run_fingerprint(prompt, attachments, model_id=""):
    payload = {
        "prompt": str(prompt or ""),
        "model_id": str(model_id or ""),
        "attachments": [
            {
                "name": str(item.get("name") or ""),
                "size": int(item.get("size") or 0),
                "content_type": str(item.get("content_type") or ""),
                "sha256": str(item.get("sha256") or ""),
            }
            for item in attachments
        ],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _safe_proxy_event(event, *, thread_id, run_id):
    """Allow-list and sanitize events crossing the Django SSE proxy."""
    if not isinstance(event, dict) or event.get("type") not in _AGUI_PROXY_EVENT_TYPES:
        return None
    event = dict(event)
    event_type = event.get("type")
    if event_type in {"RUN_STARTED", "RUN_FINISHED", "RUN_ERROR"}:
        event["threadId"] = str(thread_id)
        event["runId"] = str(run_id)
    if event_type == "RUN_ERROR":
        # Upstream technical details are for server logs only.
        event["message"] = AI_CHAT_UNAVAILABLE_MESSAGE
        event["code"] = "agent_runtime_error"
        for key in ("error", "exception", "traceback", "detail"):
            event.pop(key, None)
    elif event_type == "TOOL_CALL_ARGS":
        event["delta"] = json.dumps({"status": "received"}, ensure_ascii=False, separators=(",", ":"))
    elif event_type == "TOOL_CALL_RESULT":
        event["content"] = json.dumps({"status": "completed"}, ensure_ascii=False, separators=(",", ":"))
        event.pop("result", None)
    elif event_type == "STATE_DELTA":
        from services.agent_runtime.protocols.common.ui_commands import normalize_ui_commands

        safe_delta = []
        for operation in event.get("delta") if isinstance(event.get("delta"), list) else []:
            if not isinstance(operation, dict):
                continue
            if operation.get("path") not in {"/localBusiness/uiCommands", "/localBusinessUiCommands"}:
                continue
            commands = operation.get("value")
            if not isinstance(commands, list):
                continue
            normalized = normalize_ui_commands(commands)
            if normalized:
                safe_delta.append({"op": "replace", "path": operation["path"], "value": normalized})
        if not safe_delta:
            return None
        event["delta"] = safe_delta
    elif event_type == "CUSTOM":
        if event.get("name") == "local_business.protocol":
            value = event.get("value")
            if not isinstance(value, dict):
                return None
        elif event.get("name") == "local_business.ui_command":
            from services.agent_runtime.protocols.common.ui_commands import normalize_ui_commands

            value = event.get("value")
            commands = normalize_ui_commands([value]) if isinstance(value, dict) else []
            if not commands:
                return None
            event["value"] = commands[0]
        else:
            return None
    try:
        serialized_size = len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        return None
    if serialized_size > CHAT_RUN_MAX_EVENT_BYTES:
        return None
    return event


def _record_run_event(events, event, *, thread_id, run_id, lifecycle=None):
    safe_event = _safe_proxy_event(event, thread_id=thread_id, run_id=run_id)
    if safe_event is None:
        return None
    if lifecycle is not None:
        _validate_agui_event_order(safe_event, lifecycle)
    if len(events) >= CHAT_RUN_MAX_EVENTS:
        raise AgentRuntimeError("AG-UI event limit exceeded")
    current_size = sum(
        len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        for item in events
    )
    event_size = len(json.dumps(safe_event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if current_size + event_size > CHAT_RUN_MAX_EVENT_BYTES:
        raise AgentRuntimeError("AG-UI event payload limit exceeded")
    events.append(safe_event)
    return safe_event


def _validate_agui_event_order(event, lifecycle):
    """Enforce causal AG-UI lifecycle before forwarding or persisting events."""
    event_type = event.get("type") if isinstance(event, dict) else ""
    started = bool(lifecycle.get("started"))
    terminal = bool(lifecycle.get("terminal"))
    if event_type == "RUN_STARTED":
        if started or terminal:
            raise AgentRuntimeError("AG-UI stream содержит повторный RUN_STARTED")
        lifecycle["started"] = True
        return
    if event_type in {"RUN_FINISHED", "RUN_ERROR"}:
        if not started or terminal:
            raise AgentRuntimeError("AG-UI stream нарушает порядок терминального события")
        lifecycle["terminal"] = True
        return
    if event_type in {
        "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
        "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT",
        "STATE_SNAPSHOT", "STATE_DELTA", "CUSTOM",
    } and (not started or terminal):
        raise AgentRuntimeError("AG-UI stream содержит событие до RUN_STARTED")


def _sse_event_text(event):
    return "data: " + json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n\n"


def _run_replay_response(run):
    events = []
    lifecycle = {"started": False, "terminal": False}
    for raw_event in (run.metadata or {}).get("events") or []:
        safe_event = _safe_proxy_event(
            raw_event,
            thread_id=run.session.external_id,
            run_id=run.run_id,
        )
        if safe_event is None:
            continue
        try:
            _validate_agui_event_order(safe_event, lifecycle)
        except AgentRuntimeError:
            events = []
            break
        if len(events) >= CHAT_RUN_MAX_EVENTS:
            break
        events.append(safe_event)
    if not events or not lifecycle["started"] or not lifecycle["terminal"]:
        event_type = "RUN_ERROR" if run.status == ChatRun.Status.FAILED else "RUN_FINISHED"
        events = [
            {"type": "RUN_STARTED", "threadId": str(run.session.external_id), "runId": run.run_id},
            {"type": event_type, "threadId": str(run.session.external_id), "runId": run.run_id},
        ]

    def replay():
        for event in events:
            if isinstance(event, dict):
                yield _sse_event_text(event)

    response = StreamingHttpResponse(replay(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


def _prepare_page_context(request, message):
    envelope_value = request.POST.get("page_context") or request.POST.get("context_envelope") or ""
    if envelope_value:
        try:
            envelope = json.loads(envelope_value) if isinstance(envelope_value, str) else envelope_value
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValidationError("Некорректный контекст страницы.") from exc
        if not isinstance(envelope, dict):
            raise ValidationError("Некорректный контекст страницы.")
        # Browser clients send {envelope, context_version, context_hint}; the
        # resolver must only see the signed context envelope itself.
        wrapper = envelope if "envelope" in envelope else None
        context_hint = request.POST.get("context_hint", "")
        context_version = request.POST.get("context_version", "")
        envelope = wrapper.get("envelope") if wrapper is not None else envelope
        if wrapper is not None:
            context_hint = wrapper.get("context_hint", context_hint)
            context_version = wrapper.get("context_version", context_version)
        if not envelope:
            bind_page_context_to_message(
                user=request.user, message=message,
                window_id="", context_version="", context_hint=context_hint,
            )
            return
        if not isinstance(envelope, dict):
            raise ValidationError("Некорректный контекст страницы.")
        result = update_window_context_snapshot(request.user, envelope)
        bind_page_context_to_message(
            user=request.user,
            message=message,
            window_id=result.snapshot.window_id,
            context_version=result.snapshot.context_version or context_version,
            context_hint=context_hint,
        )
    else:
        bind_page_context_to_message(
            user=request.user,
            message=message,
            window_id=request.POST.get("window_id", ""),
            context_version=request.POST.get("context_version", ""),
            context_hint=request.POST.get("context_hint", ""),
        )
        if message.metadata.get("page_context_status") == "context_stale":
            raise ValidationError("Контекст страницы устарел.")


class AIChatPrepareTurnView(LoginRequiredMixin, View):
    """Create one immutable prepared user turn, idempotently by run_id."""

    http_method_names = ["post"]

    def post(self, request, external_id):
        session = get_object_or_404(
            ChatSession.objects.filter(user=request.user, status=ChatSession.Status.ACTIVE),
            external_id=external_id,
        )
        try:
            run_id = _validate_chat_run_id(request.POST.get("run_id"))
            prompt = str(request.POST.get("prompt", "") or "").strip()
            requested_surface = request.POST.get("surface") or ""
            default_surface = CHAT_SURFACE_SIDEBAR if session.channel == ChatSession.Channel.SIDEBAR else CHAT_SURFACE_FULL_PAGE
            surface = requested_surface if requested_surface in {CHAT_SURFACE_SIDEBAR, CHAT_SURFACE_FULL_PAGE} else default_surface
            max_prompt_chars = int(get_chat_settings(surface).get("max_prompt_chars") or 10000)
            if len(prompt) > max_prompt_chars:
                raise ValidationError("Сообщение слишком длинное.")

            # Resolve slash commands on the server. `/commands` is a UI action,
            # not a model prompt and therefore cannot become a prepared turn.
            if prompt.startswith("/"):
                cmd_spec, remainder = resolve_command(prompt)
                if cmd_spec and cmd_spec.get("handler") == "commands":
                    raise ValidationError("Команда списка недоступна как сообщение.")
                if cmd_spec:
                    template = cmd_spec.get("prompt_template", "")
                    prompt = template.replace("{input}", remainder) if remainder else template
                else:
                    custom = list(SlashCommand.objects.filter(user=request.user))
                    custom_cmd, remainder = resolve_custom_command(prompt, custom)
                    if custom_cmd:
                        prompt = custom_cmd.template.replace("{input}", remainder) if remainder else custom_cmd.template
            if len(prompt) > max_prompt_chars:
                raise ValidationError("Раскрытая команда слишком длинная.")
            uploads = request.FILES.getlist("files")
            if len(uploads) > CHAT_ATTACHMENT_MAX_COUNT:
                raise ValidationError("Слишком много вложений.")
            attachment_meta = [validate_chat_attachment(upload) for upload in uploads]
            if not prompt:
                raise ValidationError("Сообщение пустое.")
        except ValidationError as exc:
            return JsonResponse({"error": str(exc.messages[0] if hasattr(exc, "messages") else exc)}, status=400)

        try:
            with transaction.atomic():
                session = ChatSession.objects.select_for_update().get(pk=session.pk)
                if session.status != ChatSession.Status.ACTIVE:
                    return JsonResponse({"error": "Сессия недоступна."}, status=404)
                existing = ChatRun.objects.select_for_update().filter(session=session, run_id=run_id).first()
                if existing:
                    frozen_model_id = (existing.metadata or {}).get("model_id", "")
                    fingerprint = _chat_run_fingerprint(prompt, attachment_meta, frozen_model_id)
                    if (existing.metadata or {}).get("request_fingerprint") != fingerprint:
                        return JsonResponse({"error": "run_id уже использован для другого содержимого."}, status=409)
                    return JsonResponse(_chat_run_payload(existing))
                # The selected model belongs to the server-owned session.  A
                # browser field named model_id is deliberately ignored here.
                model_id = (session.metadata or {}).get("model_id", "")
                conversation_id = (session.metadata or {}).get("conversation_id") or str(uuid.uuid4())
                user_msg = append_chat_message(
                    session=session,
                    role=ChatMessage.Role.USER,
                    content=prompt,
                    metadata={
                        "conversation_id": conversation_id,
                        "run_id": run_id,
                        "origin_channel": session.channel,
                        "surface": surface,
                        "prepared": True,
                    },
                )
                _prepare_page_context(request, user_msg)
                for upload, metadata in zip(uploads, attachment_meta):
                    ChatAttachment.objects.create(
                        message=user_msg,
                        file=upload,
                        file_type=metadata["file_type"],
                        file_name=metadata["name"],
                        file_size=metadata["size"],
                    )
                run = ChatRun.objects.create(
                    session=session,
                    run_id=run_id,
                    user_message=user_msg,
                    metadata={
                        "conversation_id": conversation_id,
                        "surface": surface,
                        "attachment_count": len(uploads),
                        "model_id": model_id,
                        "request_fingerprint": _chat_run_fingerprint(prompt, attachment_meta, model_id),
                        "attachments": [
                            {"name": item["name"], "size": item["size"], "content_type": item["content_type"], "sha256": item["sha256"]}
                            for item in attachment_meta
                        ],
                    },
                )
        except IntegrityError:
            run = ChatRun.objects.get(session=session, run_id=run_id)
            if (run.metadata or {}).get("request_fingerprint") != _chat_run_fingerprint(
                prompt, attachment_meta, (run.metadata or {}).get("model_id", "")
            ):
                return JsonResponse({"error": "run_id уже использован для другого содержимого."}, status=409)
        except PermissionDenied as exc:
            return JsonResponse({"error": "Недостаточно прав для контекста страницы."}, status=403)
        except ValidationError as exc:
            return JsonResponse({"error": str(exc.messages[0] if hasattr(exc, "messages") else exc)}, status=400)
        return JsonResponse(_chat_run_payload(run), status=201)


class AIChatRunView(LoginRequiredMixin, View):
    """Run a prepared turn through the canonical AG-UI runtime endpoint."""

    http_method_names = ["post"]

    def post(self, request, external_id):
        session = get_object_or_404(
            ChatSession.objects.filter(user=request.user, status=ChatSession.Status.ACTIVE),
            external_id=external_id,
        )
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
            run_id = _validate_chat_run_id(body.get("runId"))
        except (json.JSONDecodeError, AttributeError, ValidationError) as exc:
            message = exc.messages[0] if isinstance(exc, ValidationError) else "Некорректное тело JSON."
            return JsonResponse({"error": message}, status=400)
        if str(body.get("threadId") or "") != str(session.external_id):
            return JsonResponse({"error": "Сессия запуска не совпадает с адресом запроса."}, status=400)

        with transaction.atomic():
            session = ChatSession.objects.select_for_update().get(pk=session.pk)
            if session.status != ChatSession.Status.ACTIVE:
                return JsonResponse({"error": "Сессия недоступна."}, status=404)
            # Keep FOR UPDATE on ChatRun itself. PostgreSQL rejects row locks
            # on nullable outer joins, and related messages do not need locks.
            run = ChatRun.objects.select_for_update().filter(
                session=session, run_id=run_id
            ).first()
            if not run or run.user_message.role != ChatMessage.Role.USER:
                return JsonResponse({"error": "Подготовленный ход не найден."}, status=404)
            if run.status in {ChatRun.Status.COMPLETED, ChatRun.Status.FAILED}:
                return _run_replay_response(run)
            if run.status == ChatRun.Status.RUNNING:
                lease_seconds = int(getattr(settings, "LOCAL_BUSINESS_AI_CHAT_RUN_STALE_LEASE_SECONDS", 900))
                lease_anchor = run.started_at or run.prepared_at
                if lease_anchor and lease_anchor <= timezone.now() - timezone.timedelta(seconds=lease_seconds):
                    metadata = dict(run.metadata or {})
                    metadata.setdefault("request_id", str(uuid.uuid4()))
                    metadata.setdefault("conversation_id", str(uuid.uuid4()))
                    run.metadata = metadata
                    run.save(update_fields=["metadata"])
                    _finish_chat_run(
                        run,
                        [],
                        {"content": [], "error": {"message": "Истёк срок выполнения запуска."}, "tool_trace": [], "ui_commands": []},
                        failed=True,
                        failure_exc=AgentRuntimeError("stale agent runtime lease"),
                    )
                    run.refresh_from_db()
                    return _run_replay_response(run)
                return JsonResponse({"error": "Запуск уже выполняется."}, status=409)
            # The session lock serializes admission of all prepared runs.  The
            # conditional DB constraint is the final guard, while this block
            # gives stale runs a safe terminal state before a new run starts.
            lease_seconds = int(getattr(settings, "LOCAL_BUSINESS_AI_CHAT_RUN_STALE_LEASE_SECONDS", 900))
            stale_before = timezone.now() - timezone.timedelta(seconds=lease_seconds)
            other_running = list(
                ChatRun.objects.select_for_update()
                .filter(session=session, status=ChatRun.Status.RUNNING)
                .exclude(pk=run.pk)
                .order_by("started_at", "id")
            )
            for other in other_running:
                lease_anchor = other.started_at or other.prepared_at
                if not lease_anchor or lease_anchor > stale_before:
                    return JsonResponse({"error": "Запуск уже выполняется."}, status=409)
                stale_metadata = dict(other.metadata or {})
                stale_metadata.setdefault("request_id", str(uuid.uuid4()))
                stale_metadata.setdefault("conversation_id", str(uuid.uuid4()))
                other.metadata = stale_metadata
                other.save(update_fields=["metadata"])
                _finish_chat_run(
                    other,
                    [],
                    {"content": [], "error": {"message": "Истёк срок выполнения запуска."}, "tool_trace": [], "ui_commands": []},
                    failed=True,
                    failure_exc=AgentRuntimeError("stale agent runtime lease"),
                )
            run.status = ChatRun.Status.RUNNING
            run.started_at = timezone.now()
            metadata = dict(run.metadata or {})
            metadata["request_id"] = str(uuid.uuid4())
            run.metadata = metadata
            run.save(update_fields=["status", "started_at", "metadata"])

        # The model is frozen at prepare time.  Session settings may change
        # while a prepared turn waits in the client queue.
        model_id = (run.metadata or {}).get("model_id", "")
        actor_payload = build_actor_payload(
            user=request.user,
            session=session,
            driver=DRIVER_NATIVE,
            model_id=model_id,
            page_context=build_runtime_page_context(run.user_message),
        )
        actor_payload["actor"]["conversation_id"] = (run.metadata or {}).get("conversation_id", "")
        actor_payload["actor"]["request_id"] = (run.metadata or {}).get("request_id", "")
        actor_payload["actor"]["origin_channel"] = session.channel
        actor_payload["origin_channel"] = session.channel
        actor_payload["session_id"] = str(session.external_id)
        actor_payload["signature"] = sign_actor_payload(actor_payload)
        runtime_payload = {
            "threadId": str(session.external_id),
            "runId": run.run_id,
            "parentRunId": "",
            "state": {},
            "messages": agui_messages_from_history(
                serialize_session_history(
                    session,
                    final_user_message=run.user_message,
                    surface=(run.metadata or {}).get("surface"),
                )
            ),
            "tools": [],
            "context": [],
            "forwardedProps": actor_payload,
            "resume": [],
        }

        def stream_generator():
            events = []
            collector = {"content": [], "error": None, "ui_commands": [], "tool_trace": [], "tools_by_id": {}}
            lifecycle = {"started": False, "terminal": False}
            buffer = ""
            terminal = None
            try:
                for chunk in AgentRuntimeClient().ag_ui_stream(runtime_payload):
                    parsed, buffer = parse_agui_sse_events(buffer, chunk)
                    for event in parsed:
                        event_type = event.get("type")
                        event = _safe_proxy_event(
                            event, thread_id=session.external_id, run_id=run.run_id
                        )
                        if event is None:
                            continue
                        event_type = event.get("type")
                        if event_type in {"RUN_FINISHED", "RUN_ERROR"}:
                            # A successful empty terminal is not a valid model
                            # outcome because attachment bodies are not model input.
                            if event_type == "RUN_FINISHED" and not "".join(collector.get("content", [])).strip():
                                event = {
                                    "type": "RUN_ERROR",
                                    "threadId": str(session.external_id),
                                    "runId": run.run_id,
                                    "message": AI_CHAT_UNAVAILABLE_MESSAGE,
                                    "code": "empty_assistant_response",
                                }
                                event_type = "RUN_ERROR"
                        event = _record_run_event(
                            events,
                            event,
                            thread_id=session.external_id,
                            run_id=run.run_id,
                            lifecycle=lifecycle,
                        )
                        if event is None:
                            continue
                        collect_agui_event(event, collector)
                        if event_type in {"RUN_FINISHED", "RUN_ERROR"}:
                            terminal = event_type
                            break
                        yield _sse_event_text(event)
                    if terminal:
                        break
                if not terminal:
                    parsed, _ = parse_agui_sse_events(buffer, "\n\n")
                    for event in parsed:
                        event_type = event.get("type")
                        event = _safe_proxy_event(
                            event, thread_id=session.external_id, run_id=run.run_id
                        )
                        if event is None:
                            continue
                        event_type = event.get("type")
                        if event_type in {"RUN_FINISHED", "RUN_ERROR"}:
                            if event_type == "RUN_FINISHED" and not "".join(collector.get("content", [])).strip():
                                event = {"type": "RUN_ERROR", "threadId": str(session.external_id), "runId": run.run_id, "message": AI_CHAT_UNAVAILABLE_MESSAGE, "code": "empty_assistant_response"}
                                event_type = "RUN_ERROR"
                        event = _record_run_event(
                            events,
                            event,
                            thread_id=session.external_id,
                            run_id=run.run_id,
                            lifecycle=lifecycle,
                        )
                        if event is None:
                            continue
                        collect_agui_event(event, collector)
                        if event_type in {"RUN_FINISHED", "RUN_ERROR"}:
                            terminal = event_type
                            break
                        yield _sse_event_text(event)
                if terminal not in {"RUN_FINISHED", "RUN_ERROR"}:
                    raise AgentRuntimeError("AG-UI stream завершён без терминального события")
            except Exception as exc:
                logger.warning("Canonical AG-UI run failed: run=%s error_type=%s", run.run_id, exc.__class__.__name__)
                _finish_chat_run(run, events, collector, failed=True, failure_exc=exc)
                run.refresh_from_db(fields=["status", "metadata", "assistant_message"])
                terminal_event = next(
                    (
                        event
                        for event in reversed((run.metadata or {}).get("events") or [])
                        if isinstance(event, dict) and event.get("type") in {"RUN_FINISHED", "RUN_ERROR"}
                    ),
                    None,
                )
                if not any(event.get("type") == "RUN_STARTED" for event in events):
                    started_event = next(
                        (
                            event
                            for event in (run.metadata or {}).get("events") or []
                            if isinstance(event, dict) and event.get("type") == "RUN_STARTED"
                        ),
                        None,
                    )
                    if started_event:
                        yield _sse_event_text(started_event)
                if terminal_event:
                    yield _sse_event_text(terminal_event)
                return
            except GeneratorExit:
                # A disconnected client must never make the same run eligible
                # for execution again. Persist it as a failed, replayable run.
                _finish_chat_run(run, events, collector, failed=True, failure_exc=AgentRuntimeError("AG-UI client disconnected"))
                raise
            _finish_chat_run(run, events, collector, failed=(terminal == "RUN_ERROR"), failure_exc=AgentRuntimeError("AG-UI runtime returned RUN_ERROR") if terminal == "RUN_ERROR" else None)
            run.refresh_from_db(fields=["status", "metadata", "assistant_message"])
            terminal_event = next(
                (
                    event
                    for event in reversed((run.metadata or {}).get("events") or [])
                    if isinstance(event, dict) and event.get("type") in {"RUN_FINISHED", "RUN_ERROR"}
                ),
                None,
            )
            if terminal_event:
                yield _sse_event_text(terminal_event)

        response = StreamingHttpResponse(stream_generator(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


def _finish_chat_run(run, events, collector, *, failed, failure_exc=None):
    with transaction.atomic():
        # Every native execution path locks ChatSession before ChatRun.  Keep
        # the same order here to avoid a PostgreSQL deadlock with a concurrent
        # admission or tool-fence transaction.
        locked_session = ChatSession.objects.select_for_update().get(pk=run.session_id)
        current = ChatRun.objects.select_for_update().get(pk=run.pk)
        current.session = locked_session
        current.user_message = ChatMessage.objects.get(pk=current.user_message_id)
        if current.status in {ChatRun.Status.COMPLETED, ChatRun.Status.FAILED}:
            return
        # Persist a canonical replay: even if an upstream proxy misbehaves,
        # there is exactly one terminal event for this run.
        normalized_events = []
        terminal_seen = False
        for event in events:
            event = _safe_proxy_event(
                event,
                thread_id=current.session.external_id,
                run_id=current.run_id,
            )
            if event is None:
                continue
            if event.get("type") in {"RUN_FINISHED", "RUN_ERROR"}:
                if terminal_seen:
                    break
                terminal_seen = True
            if len(normalized_events) >= CHAT_RUN_MAX_EVENTS:
                failed = True
                failure_exc = AgentRuntimeError("AG-UI event limit exceeded")
                break
            if sum(
                len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                for item in normalized_events
            ) + len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > CHAT_RUN_MAX_EVENT_BYTES:
                failed = True
                failure_exc = AgentRuntimeError("AG-UI event payload limit exceeded")
                break
            normalized_events.append(event)
        metadata = dict(current.metadata or {})
        metadata["tool_trace"] = [
            item for item in collector.get("tool_trace", [])[:CHAT_RUN_MAX_EVENTS]
            if isinstance(item, dict)
        ]
        metadata["ui_commands"] = [
            item for item in collector.get("ui_commands", [])[:CHAT_RUN_MAX_EVENTS]
            if isinstance(item, dict)
        ]
        content = "".join(collector.get("content", [])).strip()
        if failed:
            failure_exc = failure_exc or AgentRuntimeError("AG-UI runtime error")
            payload = record_chat_runtime_error(
                session=current.session,
                actor=current.session.user,
                user_message=current.user_message,
                exc=failure_exc,
                conversation_id=str(metadata.get("conversation_id") or ""),
                request_id=str(metadata.get("request_id") or ""),
                origin_channel=current.session.channel,
                model_id=str(metadata.get("model_id") or ""),
                runtime_method="ag_ui",
                partial_content=content[:CHAT_PARTIAL_CONTENT_MAX_LENGTH],
            )
            terminal = {
                "type": "RUN_ERROR",
                "threadId": str(current.session.external_id),
                "runId": current.run_id,
                "message": payload["message"],
                "code": payload["error_code"],
                "request_id": payload["request_id"],
                "conversation_id": payload["conversation_id"],
                "technical_trace_id": payload.get("technical_trace_id"),
            }
            normalized_events = [event for event in normalized_events if event.get("type") not in {"RUN_FINISHED", "RUN_ERROR"}]
            if not any(event.get("type") == "RUN_STARTED" for event in normalized_events):
                normalized_events.insert(0, {
                    "type": "RUN_STARTED",
                    "threadId": str(current.session.external_id),
                    "runId": current.run_id,
                })
            normalized_events.append(terminal)
            metadata["events"] = normalized_events
            current.assistant_message_id = payload.get("assistant_message_id")
        else:
            if not content:
                failed = True
                failure_exc = AgentRuntimeError("empty assistant response")
                payload = record_chat_runtime_error(
                    session=current.session, actor=current.session.user, user_message=current.user_message,
                    exc=failure_exc, conversation_id=str(metadata.get("conversation_id") or ""),
                    request_id=str(metadata.get("request_id") or ""), origin_channel=current.session.channel,
                    model_id=str(metadata.get("model_id") or ""), runtime_method="ag_ui",
                )
                normalized_events = [event for event in normalized_events if event.get("type") not in {"RUN_FINISHED", "RUN_ERROR"}]
                normalized_events.append({"type": "RUN_ERROR", "threadId": str(current.session.external_id), "runId": current.run_id, "message": payload["message"], "code": payload["error_code"], "request_id": payload["request_id"], "conversation_id": payload["conversation_id"], "technical_trace_id": payload.get("technical_trace_id")})
                metadata["events"] = normalized_events
                current.assistant_message_id = payload.get("assistant_message_id")
            else:
                if not terminal_seen:
                    normalized_events.append({"type": "RUN_FINISHED", "threadId": str(current.session.external_id), "runId": current.run_id})
                else:
                    normalized_events[-1].setdefault("threadId", str(current.session.external_id))
                    normalized_events[-1].setdefault("runId", current.run_id)
                metadata["events"] = normalized_events
                assistant = append_chat_message(
                    session=current.session,
                    role=ChatMessage.Role.ASSISTANT,
                    content=content,
                    metadata={
                        "run_id": current.run_id,
                        "error": False,
                        "runtime_method": "ag_ui",
                        "tool_trace": metadata["tool_trace"],
                        "ui_commands": metadata["ui_commands"],
                        "conversation_id": str(metadata.get("conversation_id") or ""),
                        "request_id": str(metadata.get("request_id") or ""),
                    },
                )
                current.assistant_message = assistant
                session_metadata = dict(current.session.metadata or {})
                session_metadata["conversation_id"] = str(metadata.get("conversation_id") or "")
                request_ids = list(session_metadata.get("request_ids", []))
                request_id = str(metadata.get("request_id") or "")
                if request_id and request_id not in request_ids:
                    request_ids.append(request_id)
                session_metadata["request_ids"] = request_ids
                current.session.metadata = session_metadata
                current.session.save(update_fields=["metadata", "updated_at"])
        current.status = ChatRun.Status.FAILED if failed else ChatRun.Status.COMPLETED
        current.finished_at = timezone.now()
        current.metadata = metadata
        current.save(update_fields=["assistant_message", "status", "finished_at", "metadata"])


class AIManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        from .skill_authoring import can_manage_ai_skills

        return can_manage_ai_skills(self.request.user)


class AIHubView(AIManagementMixin, TemplateView):
    template_name = "ai/hub.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        mode_labels = {"read": "Чтение", "write": "Запись", "admin": "Администрирование"}
        tool_registry = []
        for tool in settings.LOCAL_BUSINESS_AI_TOOLS["tools"]:
            tool_registry.append(
                {
                    **tool,
                    "code": tool.get("id") or tool.get("code", ""),
                    "mode_label": mode_labels.get(tool.get("mode", ""), tool.get("mode", "")),
                    "confirmation_label": "Требуется" if tool.get("requires_confirmation") else "Не требуется",
                }
            )
        context["tool_registry"] = tool_registry
        context["task_types"] = settings.LOCAL_BUSINESS_AI_TASK_TYPES["task_types"]
        context["recent_sessions"] = ChatSession.objects.all()[:10]
        context["recent_actions"] = AgentActionLog.objects.select_related("session")[:20]
        return context


class AIChatIndexView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        if configured_ai_ui_driver() == DRIVER_COPILOTKIT:
            return reverse("ai:copilotkit_chat_page")
        create_new = self.request.GET.get("new") == "1"
        if not create_new:
            session = (
                ChatSession.objects.filter(
                    user=self.request.user,
                    status=ChatSession.Status.ACTIVE,
                    channel=ChatSession.Channel.INTERNAL,
                )
                .order_by("-updated_at", "-id")
                .first()
            )
            if session:
                return reverse("ai:chat_detail", kwargs={"external_id": session.external_id})
        session = ChatSession.objects.create(user=self.request.user, title="Новый чат")
        return reverse("ai:chat_detail", kwargs={"external_id": session.external_id})


class AICopilotKitChatPageView(LoginRequiredMixin, TemplateView):
    template_name = "ai/copilotkit_chat.html"

    def dispatch(self, request, *args, **kwargs):
        if configured_ai_ui_driver() != DRIVER_COPILOTKIT:
            return redirect("ai:chat_index")
        return super().dispatch(request, *args, **kwargs)


class AIChatDetailView(LoginRequiredMixin, DetailView):
    model = ChatSession
    slug_field = "external_id"
    slug_url_kwarg = "external_id"
    template_name = "ai/chat_detail.html"
    context_object_name = "chat_session"

    def get_queryset(self):
        return ChatSession.objects.filter(
            user=self.request.user,
            status=ChatSession.Status.ACTIVE,
        ).prefetch_related("messages", "messages__attachments")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["chat_sessions"] = ChatSession.objects.filter(
            user=self.request.user,
            status=ChatSession.Status.ACTIVE,
        ).order_by("-updated_at", "-id")[:20]
        context["ai_models"] = settings.LOCAL_BUSINESS_AI_MODELS
        context["current_model_id"] = self.object.metadata.get("model_id", "")
        return context


class AIChatSessionConfigView(LoginRequiredMixin, View):
    """Return the owned session snapshot consumed by the native full-page mount."""

    http_method_names = ["get"]

    def get(self, request, external_id):
        session = get_object_or_404(
            ChatSession.objects.filter(user=request.user, status=ChatSession.Status.ACTIVE),
            external_id=external_id,
        )
        return JsonResponse(build_full_page_ai_ui_config(user=request.user, session=session))


class AIPageContextUpdateView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        if not allow_page_context_update(request.user.id):
            return JsonResponse({"error": "Слишком много обновлений контекста страницы."}, status=429)
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Некорректное тело JSON."}, status=400)
        try:
            sanitized = sanitize_page_context_envelope(payload)
            result = update_window_context_snapshot(request.user, sanitized)
        except ValidationError as exc:
            return JsonResponse({"error": exc.messages[0] if hasattr(exc, "messages") else str(exc)}, status=400)
        except PermissionDenied:
            return JsonResponse({"error": "Объект контекста недоступен."}, status=403)
        snapshot = result.snapshot
        return JsonResponse(
            {
                "status": "ok",
                "created": result.created,
                "window_id": snapshot.window_id,
                "context_version": snapshot.context_version,
                "context_hash": snapshot.context_hash,
                "context_hint": snapshot.resolved_summary.get("context_hint", ""),
            }
        )


class AIUIConfigView(LoginRequiredMixin, View):
    http_method_names = ["get"]

    def get(self, request):
        driver = configured_ai_ui_driver()
        if driver not in {DRIVER_COPILOTKIT, DRIVER_NATIVE}:
            return JsonResponse({"enabled": False, "driver": driver, "error": "AI UI driver отключен."}, status=404)
        runtime_url = ""
        if driver == DRIVER_NATIVE:
            session = get_or_create_sidebar_session(request.user)
            runtime_url = reverse("ai:chat_run", kwargs={"external_id": session.external_id})
        return JsonResponse(
            build_sidebar_ai_ui_config(
                user=request.user,
                driver=driver,
                runtime_url=runtime_url,
            )
        )


class AICopilotKitConfigView(LoginRequiredMixin, View):
    http_method_names = ["get"]

    def get(self, request):
        if configured_ai_ui_driver() != DRIVER_COPILOTKIT:
            return JsonResponse({"enabled": False, "error": "CopilotKit отключен."}, status=404)

        return JsonResponse(
            build_sidebar_ai_ui_config(
                user=request.user,
                driver=DRIVER_COPILOTKIT,
                runtime_url=settings.LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL,
                agent_id=settings.LOCAL_BUSINESS_COPILOTKIT_AGENT_ID,
            )
        )


class AIUISidebarSessionNewView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        driver = configured_ai_ui_driver()
        if driver not in {DRIVER_COPILOTKIT, DRIVER_NATIVE}:
            return JsonResponse({"enabled": False, "driver": driver, "error": "AI UI driver отключен."}, status=404)

        create_new_sidebar_session(request.user)
        runtime_url = settings.LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL
        if driver == DRIVER_NATIVE:
            session = get_or_create_sidebar_session(request.user)
            runtime_url = reverse("ai:chat_run", kwargs={"external_id": session.external_id})
        return JsonResponse(
            build_sidebar_ai_ui_config(
                user=request.user,
                driver=driver,
                runtime_url=runtime_url,
                agent_id=settings.LOCAL_BUSINESS_COPILOTKIT_AGENT_ID,
            )
        )


class AIUISidebarSessionClearView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        driver = configured_ai_ui_driver()
        if driver not in {DRIVER_COPILOTKIT, DRIVER_NATIVE}:
            return JsonResponse({"enabled": False, "driver": driver, "error": "AI UI driver отключен."}, status=404)

        session = get_or_create_sidebar_session(request.user)
        session = clear_sidebar_session(session)
        runtime_url = settings.LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL
        if driver == DRIVER_NATIVE:
            runtime_url = reverse("ai:chat_run", kwargs={"external_id": session.external_id})
        return JsonResponse(
            build_sidebar_ai_ui_config(
                user=request.user,
                driver=driver,
                runtime_url=runtime_url,
                agent_id=settings.LOCAL_BUSINESS_COPILOTKIT_AGENT_ID,
            )
        )


class AIChatUpdateModelView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(
            ChatSession.objects.filter(user=request.user, status=ChatSession.Status.ACTIVE),
            external_id=external_id,
        )
        try:
            body = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Некорректное тело JSON."}, status=400)
        if not isinstance(body, dict):
            return JsonResponse({"error": "Тело JSON должно быть объектом."}, status=400)
        model_id = body.get("model_id", "")
        if not isinstance(model_id, str):
            return JsonResponse({"error": "model_id должен быть строкой."}, status=400)
        valid_ids = {m["id"] for m in settings.LOCAL_BUSINESS_AI_MODELS}
        if model_id and model_id not in valid_ids:
            return JsonResponse({"error": "Некорректный model_id."}, status=400)
        with transaction.atomic():
            session = ChatSession.objects.select_for_update().filter(
                pk=session.pk, status=ChatSession.Status.ACTIVE
            ).first()
            if session is None:
                return JsonResponse({"error": "Сессия недоступна."}, status=404)
            session.metadata = {**session.metadata, "model_id": model_id}
            session.save(update_fields=["metadata", "updated_at"])
            return JsonResponse({"status": "ok", "model_id": model_id})


class AIChatUpdateTitleView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(
            ChatSession.objects.filter(user=request.user, status=ChatSession.Status.ACTIVE),
            external_id=external_id,
        )
        try:
            body = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Некорректное тело JSON."}, status=400)
        if not isinstance(body, dict):
            return JsonResponse({"error": "Тело JSON должно быть объектом."}, status=400)
        title_value = body.get("title", "")
        if not isinstance(title_value, str):
            return JsonResponse({"error": "title должен быть строкой."}, status=400)
        title = title_value.strip()[:50]
        if not title:
            return JsonResponse({"error": "Заголовок не может быть пустым."}, status=400)
        with transaction.atomic():
            session = ChatSession.objects.select_for_update().filter(
                pk=session.pk, status=ChatSession.Status.ACTIVE
            ).first()
            if session is None:
                return JsonResponse({"error": "Сессия недоступна."}, status=404)
            session.title = title
            session.save(update_fields=["title", "updated_at"])
            return JsonResponse({"status": "ok", "title": session.title})


class AIChatGenerateTitleView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        from .services import DEFAULT_CHAT_TITLE

        session = get_object_or_404(
            ChatSession.objects.filter(user=request.user, status=ChatSession.Status.ACTIVE).prefetch_related("messages"),
            external_id=external_id,
        )
        if session.title and session.title != DEFAULT_CHAT_TITLE:
            return JsonResponse({"status": "ok", "title": session.title, "generated": False})

        new_title = generate_session_title(session)
        if new_title:
            with transaction.atomic():
                session = ChatSession.objects.select_for_update().filter(
                    pk=session.pk, status=ChatSession.Status.ACTIVE
                ).first()
                if session is None:
                    return JsonResponse({"status": "ok", "title": DEFAULT_CHAT_TITLE, "generated": False})
                if session.title and session.title != DEFAULT_CHAT_TITLE:
                    return JsonResponse({"status": "ok", "title": session.title, "generated": False})
                session.title = new_title
                session.save(update_fields=["title", "updated_at"])
                return JsonResponse({"status": "ok", "title": session.title, "generated": True})

        return JsonResponse({"status": "ok", "title": session.title or DEFAULT_CHAT_TITLE, "generated": False})


class AIChatDeleteView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(
            ChatSession.objects.filter(user=request.user, status=ChatSession.Status.ACTIVE),
            external_id=external_id,
        )
        with transaction.atomic():
            session = ChatSession.objects.select_for_update().filter(
                pk=session.pk, status=ChatSession.Status.ACTIVE
            ).first()
            if session is None:
                return JsonResponse({"error": "Сессия недоступна."}, status=404)
            archive_chat_session(session, reason="user_deleted")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"status": "ok"})
        return redirect("ai:chat_index")


@method_decorator(csrf_exempt, name="dispatch")
class AIToolExecuteView(View):
    http_method_names = ["post"]

    def dispatch(self, request, *args, **kwargs):
        token_error = reject_invalid_gateway_token(request)
        if token_error:
            return token_error
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, tool_code):
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Некорректное тело JSON."}, status=400)

        actor_context = body.get("actor", {})
        payload = body.get("payload", {})
        session_id = body.get("session_id")
        actor_error = validate_gateway_actor(actor_context, session_id)
        if actor_error:
            return actor_error
        # Extract identity/correlation fields forwarded from the runtime
        conversation_id = body.get("conversation_id", "")
        request_id = body.get("request_id", str(uuid.uuid4()))
        origin_channel = body.get("origin_channel", "")
        actor_version = body.get("actor_version", "")
        try:
            result = execute_tool(
                tool_code=tool_code,
                actor_context=actor_context,
                payload=payload,
                session_external_id=session_id,
                conversation_id=conversation_id,
                request_id=request_id,
                origin_channel=origin_channel,
                actor_version=actor_version,
            )
        except UnknownToolError:
            return JsonResponse({"error": "Неизвестный инструмент."}, status=404)
        except PermissionDenied:
            return JsonResponse({"error": "Контекст запуска недоступен."}, status=403)
        except ValidationError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

        if result.get("ok"):
            return JsonResponse(result, status=200)
        return JsonResponse(result, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class AIToolConfirmView(View):
    http_method_names = ["post"]

    def dispatch(self, request, *args, **kwargs):
        token_error = reject_invalid_gateway_token(request)
        if token_error:
            return token_error
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, token):
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Некорректное тело JSON."}, status=400)

        confirmed = body.get("confirmed", False)
        actor_context = body.get("actor", {})
        session_id = body.get("session_id")
        actor_error = validate_gateway_actor(actor_context, session_id)
        if actor_error:
            return actor_error
        conversation_id = body.get("conversation_id", "")
        request_id = body.get("request_id", str(uuid.uuid4()))
        origin_channel = body.get("origin_channel", "")
        actor_version = body.get("actor_version", "")

        result = execute_pending_action(
            token=token,
            confirmed=confirmed,
            actor_context=actor_context,
            session_external_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            origin_channel=origin_channel,
            actor_version=actor_version,
        )

        if result.get("ok"):
            return JsonResponse(result, status=200)
        return JsonResponse(result, status=400)

@method_decorator(csrf_exempt, name="dispatch")
class AISkillCatalogView(View):
    def get(self, request):
        token_error = reject_invalid_gateway_token(request)
        if token_error:
            return token_error

        from .skills_service import discover_skills
        return JsonResponse({"skills": discover_skills()})

@method_decorator(csrf_exempt, name="dispatch")
class AISkillLoadView(View):
    def get(self, request, skill_id):
        token_error = reject_invalid_gateway_token(request)
        if token_error:
            return token_error

        from .skills_service import load_skill_content
        content = load_skill_content(skill_id)
        if content:
            return JsonResponse({"id": skill_id, "instructions": content})
        return JsonResponse({"error": "Навык не найден."}, status=404)


class SlashCommandListView(LoginRequiredMixin, View):
    """GET /ai/chat/<uuid>/commands/ — list all available commands."""

    def get(self, request, external_id):
        session = get_object_or_404(
            ChatSession.objects.filter(user=request.user),
            external_id=external_id,
        )
        predefined = get_predefined_commands()
        custom = SlashCommand.objects.filter(user=request.user)
        return JsonResponse({
            "predefined": [
                {
                    "name": c["name"],
                    "aliases": c.get("aliases", []),
                    "description": c["description"],
                    "requires_input": c.get("requires_input", False),
                    "is_custom": False,
                }
                for c in predefined
            ],
            "custom": [
                {
                    "name": c.name,
                    "shortcut": c.shortcut,
                    "description": c.description,
                    "template": c.template,
                    "is_custom": True,
                }
                for c in custom
            ],
        })


class SlashCommandCreateView(LoginRequiredMixin, View):
    """POST /ai/chat/commands/create/ — create a custom command."""

    def post(self, request):
        try:
            body = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Некорректное тело JSON."}, status=400)

        name = body.get("name", "").strip().lstrip("/").lower()
        shortcut = body.get("shortcut", "").strip().lstrip("/").lower()
        description = body.get("description", "").strip()
        template = body.get("template", "").strip()

        if not name or not template:
            return JsonResponse({"error": "Имя и шаблон обязательны."}, status=400)

        if len(name) > 64:
            return JsonResponse({"error": "Имя команды слишком длинное (максимум 64 символа)."}, status=400)

        # Prevent collision with predefined command names and aliases
        predefined_names = set()
        for cmd in get_predefined_commands():
            predefined_names.add(cmd["name"])
            predefined_names.update(cmd.get("aliases", []))
        if name in predefined_names or shortcut in predefined_names:
            return JsonResponse(
                {"error": "Имя или сокращение совпадает с встроенной командой."}, status=400
            )

        if SlashCommand.objects.filter(user=request.user, name=name).exists():
            return JsonResponse(
                {"error": "Команда с таким именем уже существует."}, status=400
            )

        cmd = SlashCommand.objects.create(
            user=request.user,
            name=name,
            shortcut=shortcut,
            description=description,
            template=template,
        )
        return JsonResponse({
            "status": "ok",
            "command": {
                "id": cmd.id,
                "name": cmd.name,
                "shortcut": cmd.shortcut,
                "description": cmd.description,
                "template": cmd.template,
            },
        })


class SlashCommandDeleteView(LoginRequiredMixin, View):
    """POST /ai/chat/commands/<int:cmd_id>/delete/ — delete a custom command."""

    def post(self, request, cmd_id):
        cmd = get_object_or_404(
            SlashCommand.objects.filter(user=request.user),
            pk=cmd_id,
        )
        cmd.delete()
        return JsonResponse({"status": "ok"})
