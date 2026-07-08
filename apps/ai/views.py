import json
import uuid
import logging
import hmac
import hashlib
import time

from django.conf import settings
from django.contrib import messages
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
from django.views.decorators.csrf import csrf_exempt

from apps.workorders.policies import can_manage_inventory

from .commands import get_predefined_commands, resolve_command, resolve_custom_command
from .forms import AIChatInputForm
from .models import AgentActionLog, ChatMessage, ChatSession, ChatAttachment, SlashCommand
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
    clear_sidebar_session,
    compact_sidebar_session,
    create_new_sidebar_session,
    generate_session_title,
    get_or_create_sidebar_session,
    normalize_session_external_id,
    serialize_session_history,
)
from .tooling import UnknownToolError, execute_pending_action, execute_tool
from .ui_runtime.actor import build_actor_payload, sign_actor_payload, signature_payload
from .ui_runtime.config import build_sidebar_ai_ui_config
from .ui_runtime.drivers import DRIVER_COPILOTKIT, DRIVER_NATIVE, configured_ai_ui_driver

logger = logging.getLogger(__name__)

CHAT_RUNTIME_ERROR_MESSAGE = (
    "Не удалось получить ответ от ИИ-сервиса. Причина: {reason}. "
    "Технический идентификатор: {request_id}."
)
PAGE_CONTEXT_RATE_LIMIT_PER_MINUTE = 120


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
    return "chat_stream_error", "внутренняя ошибка обработки чата"


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
    error_code, reason = classify_chat_runtime_error(exc)
    message = CHAT_RUNTIME_ERROR_MESSAGE.format(reason=reason, request_id=request_id)
    payload = {
        "error": True,
        "error_code": error_code,
        "message": message,
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
    append_chat_message(
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
            "streamed": runtime_method == "chat_stream",
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


def chat_surface_from_request(request, default=CHAT_SURFACE_FULL_PAGE):
    surface = request.POST.get("surface") or default
    return CHAT_SURFACE_SIDEBAR if surface == CHAT_SURFACE_SIDEBAR else CHAT_SURFACE_FULL_PAGE


def bind_request_context_to_message(request, user_msg):
    return bind_page_context_to_message(
        user=request.user,
        message=user_msg,
        window_id=request.POST.get("window_id", ""),
        context_version=request.POST.get("context_version", ""),
        context_hint=request.POST.get("context_hint", ""),
    )


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


def latest_agui_user_text(messages):
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            return "".join(parts).strip()
    return ""


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
            "message": str(event.get("message") or "ИИ-сервис вернул ошибку."),
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


class AIManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_manage_inventory(self.request.user)


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
        context["form"] = AIChatInputForm()
        context["ai_models"] = settings.LOCAL_BUSINESS_AI_MODELS
        context["current_model_id"] = self.object.metadata.get("model_id", "")
        context["predefined_commands"] = get_predefined_commands()
        context["custom_commands"] = list(
            SlashCommand.objects.filter(user=self.request.user).values(
                "id", "name", "shortcut", "description", "template"
            )
        )
        return context


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
            runtime_url = reverse("ai:ui_ag_ui_run")
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
            runtime_url = reverse("ai:ui_ag_ui_run")
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
        clear_sidebar_session(session)
        runtime_url = settings.LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL
        if driver == DRIVER_NATIVE:
            runtime_url = reverse("ai:ui_ag_ui_run")
        return JsonResponse(
            build_sidebar_ai_ui_config(
                user=request.user,
                driver=driver,
                runtime_url=runtime_url,
                agent_id=settings.LOCAL_BUSINESS_COPILOTKIT_AGENT_ID,
            )
        )


class AIUIAGUIRunProxyView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        if configured_ai_ui_driver() != DRIVER_NATIVE:
            return JsonResponse({"error": "Native AI UI отключен."}, status=404)
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Некорректное тело JSON."}, status=400)

        session = get_or_create_sidebar_session(request.user)
        model_id = (session.metadata or {}).get("model_id", "")
        conversation_id = (session.metadata or {}).get("conversation_id") or str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        client_messages = body.get("messages") if isinstance(body.get("messages"), list) else []
        prompt = latest_agui_user_text(client_messages)
        chat_settings = get_chat_settings(CHAT_SURFACE_SIDEBAR)
        max_prompt_chars = int(chat_settings.get("max_prompt_chars") or 10000)
        if len(prompt) > max_prompt_chars:
            prompt = prompt[:max_prompt_chars]
        forwarded = body.get("forwardedProps") if isinstance(body.get("forwardedProps"), dict) else {}
        page_context = forwarded.get("page_context") if isinstance(forwarded.get("page_context"), dict) else {}
        user_msg = None
        runtime_page_context = {}
        if prompt:
            user_msg = append_chat_message(
                session=session,
                role=ChatMessage.Role.USER,
                content=prompt,
                metadata={
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "origin_channel": ChatSession.Channel.SIDEBAR,
                    "surface": CHAT_SURFACE_SIDEBAR,
                },
            )
            envelope = page_context.get("envelope") if isinstance(page_context.get("envelope"), dict) else {}
            if envelope:
                context_result = update_window_context_snapshot(request.user, envelope)
                bind_page_context_to_message(
                    user=request.user,
                    message=user_msg,
                    window_id=context_result.snapshot.window_id,
                    context_version=context_result.snapshot.context_version,
                    context_hint=page_context.get("context_hint", ""),
                )
                runtime_page_context = build_runtime_page_context(user_msg)

        actor_payload = build_actor_payload(
            user=request.user,
            session=session,
            driver=DRIVER_NATIVE,
            model_id=model_id,
            page_context=runtime_page_context,
        )
        actor_payload["actor"]["conversation_id"] = conversation_id
        actor_payload["actor"]["request_id"] = request_id
        actor_payload["actor"]["origin_channel"] = DRIVER_NATIVE
        actor_payload["actor"]["actor_version"] = actor_payload.get("actor_version", "")
        runtime_messages = agui_messages_from_history(serialize_session_history(session)) if prompt else client_messages
        run_payload = {
            "threadId": str(session.external_id),
            "runId": str(body.get("runId") or f"run_{uuid.uuid4().hex}"),
            "parentRunId": str(body.get("parentRunId") or ""),
            "state": body.get("state") if isinstance(body.get("state"), dict) else {},
            "messages": runtime_messages,
            "tools": [],
            "context": body.get("context") if isinstance(body.get("context"), list) else [],
            "forwardedProps": actor_payload,
            "resume": body.get("resume") if isinstance(body.get("resume"), list) else [],
        }

        def stream_generator():
            collector = {
                "content": [],
                "tool_trace": [],
                "tools_by_id": {},
                "ui_commands": [],
                "error": None,
            }
            sse_buffer = ""
            try:
                for chunk in AgentRuntimeClient().ag_ui_stream(run_payload):
                    events, sse_buffer = parse_agui_sse_events(sse_buffer, chunk)
                    for event in events:
                        collect_agui_event(event, collector)
                    yield chunk
                events, sse_buffer = parse_agui_sse_events(sse_buffer, "\n\n")
                for event in events:
                    collect_agui_event(event, collector)
            except Exception as exc:
                if user_msg:
                    append_chat_message(
                        session=session,
                        role=ChatMessage.Role.ASSISTANT,
                        content="ИИ-сервис вернул ошибку.",
                        metadata={
                            "error": True,
                            "error_code": "agent_runtime_error",
                            "conversation_id": conversation_id,
                            "request_id": request_id,
                            "runtime_method": "ag_ui",
                            **context_trace_metadata(user_msg),
                        },
                    )
                    session.metadata = {
                        **(session.metadata or {}),
                        "conversation_id": conversation_id,
                        "request_ids": [*(session.metadata or {}).get("request_ids", []), request_id],
                        "last_error_request_id": request_id,
                        "last_error_code": "agent_runtime_error",
                    }
                    session.save(update_fields=["metadata", "updated_at"])
                logger.warning(
                    "Native AI UI AG-UI proxy failed: user_id=%s session=%s error_type=%s",
                    request.user.id,
                    session.external_id,
                    exc.__class__.__name__,
                )
                yield "data: " + json.dumps(
                    {
                        "type": "RUN_ERROR",
                        "message": "ИИ-сервис вернул ошибку.",
                        "code": "agent_runtime_error",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ) + "\n\n"
                return

            content = "".join(collector["content"]).strip()
            request_ids = list((session.metadata or {}).get("request_ids", []))
            if request_id not in request_ids:
                request_ids.append(request_id)
            if collector["error"]:
                if user_msg:
                    append_chat_message(
                        session=session,
                        role=ChatMessage.Role.ASSISTANT,
                        content=collector["error"]["message"],
                        metadata={
                            "error": True,
                            "error_code": collector["error"]["code"],
                            "conversation_id": conversation_id,
                            "request_id": request_id,
                            "runtime_method": "ag_ui",
                            **context_trace_metadata(user_msg),
                        },
                    )
            elif content and user_msg:
                seen_commands = set()
                ui_commands = []
                for command in collector["ui_commands"]:
                    key = json.dumps(command, ensure_ascii=False, sort_keys=True)
                    if key in seen_commands:
                        continue
                    seen_commands.add(key)
                    ui_commands.append(command)
                append_chat_message(
                    session=session,
                    role=ChatMessage.Role.ASSISTANT,
                    content=content,
                    metadata={
                        "tool_trace": collector["tool_trace"],
                        "ui_commands": ui_commands,
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                        "streamed": True,
                        "runtime_method": "ag_ui",
                        **context_trace_metadata(user_msg),
                    },
                )
                compact_sidebar_session(session)

            session.metadata = {
                **(session.metadata or {}),
                "conversation_id": conversation_id,
                "request_ids": request_ids,
            }
            if collector["error"]:
                session.metadata["last_error_request_id"] = request_id
                session.metadata["last_error_code"] = collector["error"]["code"]
            session.save(update_fields=["metadata", "updated_at"])

        response = StreamingHttpResponse(stream_generator(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class AIChatMessageCreateView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(ChatSession.objects.filter(user=request.user), external_id=external_id)

        prompt = request.POST.get("prompt", "").strip()
        model_id = request.POST.get("model_id", "") or session.metadata.get("model_id", "")
        surface = chat_surface_from_request(request, default=CHAT_SURFACE_SIDEBAR if session.channel == ChatSession.Channel.SIDEBAR else CHAT_SURFACE_FULL_PAGE)
        chat_settings = get_chat_settings(surface)
        max_prompt_chars = int(chat_settings.get("max_prompt_chars") or 10000)
        if len(prompt) > max_prompt_chars:
            prompt = prompt[:max_prompt_chars]
        files = request.FILES.getlist("files")

        # --- Slash command resolution ---
        if prompt.startswith("/"):
            cmd_spec, remainder = resolve_command(prompt)
            if cmd_spec:
                if cmd_spec.get("handler") == "commands":
                    custom_cmds = list(
                        SlashCommand.objects.filter(user=request.user).values(
                            "id", "name", "shortcut", "description", "template"
                        )
                    )
                    predefined_cmds = get_predefined_commands()
                    return JsonResponse({
                        "status": "command_list",
                        "predefined": [
                            {
                                "name": c["name"],
                                "aliases": c.get("aliases", []),
                                "description": c["description"],
                            }
                            for c in predefined_cmds
                        ],
                        "custom": custom_cmds,
                    })
                template = cmd_spec["prompt_template"]
                prompt = template.replace("{input}", remainder) if remainder else template
            else:
                user_cmds = list(SlashCommand.objects.filter(user=request.user))
                custom_cmd, remainder = resolve_custom_command(prompt, user_cmds)
                if custom_cmd:
                    template = custom_cmd.template
                    prompt = template.replace("{input}", remainder) if remainder else template
        # --- End slash command resolution ---

        if not prompt and not files:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"error": "Пустое сообщение"}, status=400)
            messages.error(request, "Сообщение пустое.")
            return redirect("ai:chat_detail", external_id=session.external_id)

        conversation_id = session.metadata.get("conversation_id") or str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        user_msg = append_chat_message(
            session=session,
            role=ChatMessage.Role.USER,
            content=prompt,
            metadata={
                "conversation_id": conversation_id,
                "request_id": request_id,
                "origin_channel": session.channel,
                "surface": surface,
            },
        )
        bind_request_context_to_message(request, user_msg)

        # Handle attachments
        for f in files:
            file_type = ChatAttachment.FileType.OTHER
            content_type = f.content_type or ""
            if content_type.startswith("image/"):
                file_type = ChatAttachment.FileType.IMAGE
            elif content_type.startswith("audio/"):
                file_type = ChatAttachment.FileType.AUDIO
            elif "pdf" in content_type or "word" in content_type or "text" in content_type:
                file_type = ChatAttachment.FileType.DOCUMENT

            ChatAttachment.objects.create(
                message=user_msg,
                file=f,
                file_name=f.name,
                file_type=file_type,
                file_size=f.size
            )

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            compact_sidebar_session(session)
            return JsonResponse({"status": "ok", "message_id": user_msg.id, "model_id": model_id})

        # Чат идёт ТОЛЬКО через стриминговый путь (ai:chat_stream): ответ
        # ассистента отрисовывает SSE-клиент. Синхронный LLM-вызов удалён —
        # он держал соединение лишь до LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT
        # (90s), тогда как agent-runtime работает до LLM_DEADLINE_SECONDS
        # (300s); из-за этого рассинхрона write-инструмент мог осиротеть уже
        # после того, как пользователь получил ошибку. Не-AJAX запрос просто
        # возвращается к детальной странице сессии.
        return redirect("ai:chat_detail", external_id=session.external_id)


class AIChatMessageStreamView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(ChatSession.objects.filter(user=request.user), external_id=external_id)
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Некорректное тело JSON."}, status=400)
        msg_id = body.get("msg_id")
        prompt = body.get("prompt", "")
        surface = body.get("surface") or (CHAT_SURFACE_SIDEBAR if session.channel == ChatSession.Channel.SIDEBAR else CHAT_SURFACE_FULL_PAGE)
        surface = CHAT_SURFACE_SIDEBAR if surface == CHAT_SURFACE_SIDEBAR else CHAT_SURFACE_FULL_PAGE
        chat_settings = get_chat_settings(surface)
        max_prompt_chars = int(chat_settings.get("max_prompt_chars") or 10000)
        if len(prompt) > max_prompt_chars:
            prompt = prompt[:max_prompt_chars]
        model_id = body.get("model_id", "") or session.metadata.get("model_id", "")

        conversation_id = session.metadata.get("conversation_id") or str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        # If msg_id is provided, the message was already created by AIChatMessageCreateView
        if msg_id:
            user_msg = get_object_or_404(ChatMessage, id=msg_id, session=session)
            prompt = user_msg.content
        elif prompt:
            # Fallback for older clients that don't use the two-step upload process
            user_msg = append_chat_message(
                session=session,
                role=ChatMessage.Role.USER,
                content=prompt,
                metadata={
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "origin_channel": session.channel,
                    "surface": surface,
                },
            )
            bind_page_context_to_message(
                user=request.user,
                message=user_msg,
                window_id=body.get("window_id", ""),
                context_version=body.get("context_version", ""),
                context_hint=body.get("context_hint", ""),
            )
        else:
            return JsonResponse({"error": "Нужно указать prompt или msg_id."}, status=400)

        def stream_generator():
            client = AgentRuntimeClient()
            full_content = []
            ui_commands = []

            try:
                for event in client.chat_stream(
                    user=request.user,
                    session_id=session.external_id,
                    prompt=prompt,
                    history=serialize_session_history(session),
                    conversation_id=conversation_id,
                    request_id=request_id,
                    origin_channel=session.channel,
                    model_id=model_id,
                    page_context=build_runtime_page_context(user_msg)
                    if chat_settings.get("context_tool_enabled", True)
                    else {},
                ):
                    yield f"{event}\n\n"

                    if event.startswith("data: "):
                        data_str = event[6:]
                        if data_str != "[DONE]":
                            try:
                                data_json = json.loads(data_str)
                                if "content" in data_json:
                                    full_content.append(data_json["content"])
                                if isinstance(data_json.get("ui_command"), dict):
                                    ui_commands.append(data_json["ui_command"])
                            except (json.JSONDecodeError, TypeError):
                                pass
            except Exception as exc:
                partial_content = "".join(full_content)
                payload = record_chat_runtime_error(
                    session=session,
                    actor=request.user,
                    user_message=user_msg,
                    exc=exc,
                    conversation_id=conversation_id,
                    request_id=request_id,
                    origin_channel=session.channel,
                    model_id=model_id,
                    runtime_method="chat_stream",
                    partial_content=partial_content,
                )
                logger.warning(
                    "AI chat stream failed: request_id=%s action_id=%s error_type=%s",
                    request_id,
                    payload.get("technical_trace_id"),
                    exc.__class__.__name__,
                )
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return

            if full_content:
                append_chat_message(
                    session=session,
                    role=ChatMessage.Role.ASSISTANT,
                    content="".join(full_content),
                    metadata={
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                        "streamed": True,
                        "ui_commands": ui_commands,
                        **context_trace_metadata(user_msg),
                    },
                )
                # Сохраняем trace-контекст на уровне сессии (conversation_id +
                # накопленные request_ids). Раньше эту аудит-запись вёл
                # синхронный путь AIChatMessageCreateView; после перехода на
                # streaming-only чат её ведёт стриминговый путь, чтобы не
                # терять корреляцию диалога между ходами.
                session.metadata = {
                    **session.metadata,
                    "conversation_id": conversation_id,
                    "request_ids": [*session.metadata.get("request_ids", []), request_id],
                }
                session.save(update_fields=["metadata", "updated_at"])
                compact_sidebar_session(session)

        return StreamingHttpResponse(stream_generator(), content_type="text/event-stream")


class AIChatUpdateModelView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(ChatSession.objects.filter(user=request.user), external_id=external_id)
        try:
            body = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Некорректное тело JSON."}, status=400)
        model_id = body.get("model_id", "")
        valid_ids = {m["id"] for m in settings.LOCAL_BUSINESS_AI_MODELS}
        if model_id and model_id not in valid_ids:
            return JsonResponse({"error": "Некорректный model_id."}, status=400)
        session.metadata = {**session.metadata, "model_id": model_id}
        session.save(update_fields=["metadata", "updated_at"])
        return JsonResponse({"status": "ok", "model_id": model_id})


class AIChatUpdateTitleView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(ChatSession.objects.filter(user=request.user), external_id=external_id)
        try:
            body = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Некорректное тело JSON."}, status=400)
        title = body.get("title", "").strip()[:50]
        if not title:
            return JsonResponse({"error": "Заголовок не может быть пустым."}, status=400)
        session.title = title
        session.save(update_fields=["title", "updated_at"])
        return JsonResponse({"status": "ok", "title": session.title})


class AIChatGenerateTitleView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        from .services import DEFAULT_CHAT_TITLE

        session = get_object_or_404(
            ChatSession.objects.filter(user=request.user).prefetch_related("messages"),
            external_id=external_id,
        )
        if session.title and session.title != DEFAULT_CHAT_TITLE:
            return JsonResponse({"status": "ok", "title": session.title, "generated": False})

        new_title = generate_session_title(session)
        if new_title:
            session.title = new_title
            session.save(update_fields=["title", "updated_at"])
            return JsonResponse({"status": "ok", "title": session.title, "generated": True})

        return JsonResponse({"status": "ok", "title": session.title or DEFAULT_CHAT_TITLE, "generated": False})


class AIChatDeleteView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(ChatSession.objects.filter(user=request.user), external_id=external_id)
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
