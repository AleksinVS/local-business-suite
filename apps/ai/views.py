import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.http import HttpResponseForbidden, JsonResponse
from django.views import View
from django.views.generic import DetailView, RedirectView, TemplateView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from apps.workorders.policies import can_manage_inventory

from .forms import AIChatInputForm
from .models import AgentActionLog, ChatMessage, ChatSession
from .runtime_client import AgentRuntimeClient, AgentRuntimeError
from .services import append_chat_message, serialize_session_history
from .tooling import UnknownToolError, execute_tool


class AIManagementMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_manage_inventory(self.request.user)


class AIHubView(AIManagementMixin, TemplateView):
    template_name = "ai/hub.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["tool_registry"] = settings.LOCAL_BUSINESS_AI_TOOLS["tools"]
        context["task_types"] = settings.LOCAL_BUSINESS_AI_TASK_TYPES["task_types"]
        context["recent_sessions"] = ChatSession.objects.select_related("user")[:10]
        context["recent_actions"] = AgentActionLog.objects.select_related("actor", "session")[:20]
        return context


class AIChatIndexView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        session = (
            ChatSession.objects.filter(user=self.request.user, status=ChatSession.Status.ACTIVE)
            .order_by("-updated_at", "-id")
            .first()
        )
        if session:
            return reverse("ai:chat_detail", kwargs={"external_id": session.external_id})
        session = ChatSession.objects.create(user=self.request.user, title="Новый чат")
        return reverse("ai:chat_detail", kwargs={"external_id": session.external_id})


class AIChatDetailView(LoginRequiredMixin, DetailView):
    model = ChatSession
    slug_field = "external_id"
    slug_url_kwarg = "external_id"
    template_name = "ai/chat_detail.html"
    context_object_name = "chat_session"

    def get_queryset(self):
        return ChatSession.objects.filter(user=self.request.user).prefetch_related("messages")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["chat_sessions"] = ChatSession.objects.filter(user=self.request.user).order_by("-updated_at", "-id")[:20]
        context["form"] = AIChatInputForm()
        return context


class AIChatMessageCreateView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(ChatSession.objects.filter(user=request.user), external_id=external_id)
        form = AIChatInputForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Сообщение не прошло валидацию.")
            return redirect("ai:chat_detail", external_id=session.external_id)

        prompt = form.cleaned_data["prompt"]
        append_chat_message(session=session, role=ChatMessage.Role.USER, content=prompt)
        try:
            response = AgentRuntimeClient().chat(
                user=request.user,
                session_id=session.external_id,
                prompt=prompt,
                history=serialize_session_history(session),
            )
        except AgentRuntimeError as exc:
            append_chat_message(
                session=session,
                role=ChatMessage.Role.SYSTEM,
                content=f"Ошибка agent runtime: {exc}",
            )
            messages.error(request, "AI runtime недоступен или вернул ошибку.")
            return redirect("ai:chat_detail", external_id=session.external_id)

        append_chat_message(
            session=session,
            role=ChatMessage.Role.ASSISTANT,
            content=response["assistant_message"],
            metadata={"tool_trace": response.get("tool_trace", [])},
        )
        if not session.title:
            session.title = prompt[:80]
            session.save(update_fields=["title", "updated_at"])
        return redirect("ai:chat_detail", external_id=session.external_id)


@method_decorator(csrf_exempt, name="dispatch")
class AIToolExecuteView(View):
    http_method_names = ["post"]

    def dispatch(self, request, *args, **kwargs):
        expected_token = settings.LOCAL_BUSINESS_AI_GATEWAY_TOKEN
        gateway_token = request.headers.get("X-AI-Gateway-Token", "")
        if not expected_token or gateway_token != expected_token:
            return HttpResponseForbidden("AI gateway token is invalid.")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, tool_code):
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        actor_context = body.get("actor", {})
        payload = body.get("payload", {})
        session_id = body.get("session_id")
        try:
            result = execute_tool(
                tool_code=tool_code,
                actor_context=actor_context,
                payload=payload,
                session_external_id=session_id,
            )
            return JsonResponse(result, status=200)
        except UnknownToolError:
            return JsonResponse({"error": "Unknown tool."}, status=404)
        except PermissionDenied as exc:
            return JsonResponse({"error": str(exc)}, status=403)
        except ValidationError as exc:
            return JsonResponse({"error": exc.message}, status=400)
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=400)
