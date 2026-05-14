import json
import uuid
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
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
from .runtime_client import AgentRuntimeClient, AgentRuntimeError
from .services import append_chat_message, generate_session_title, serialize_session_history
from .tooling import UnknownToolError, execute_pending_action, execute_tool

logger = logging.getLogger(__name__)

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
        create_new = self.request.GET.get("new") == "1"
        if not create_new:
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
        return ChatSession.objects.filter(user=self.request.user).prefetch_related("messages", "messages__attachments")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["chat_sessions"] = ChatSession.objects.filter(user=self.request.user).order_by("-updated_at", "-id")[:20]
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


class AIChatMessageCreateView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(ChatSession.objects.filter(user=request.user), external_id=external_id)

        prompt = request.POST.get("prompt", "").strip()
        model_id = request.POST.get("model_id", "") or session.metadata.get("model_id", "")
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
                return JsonResponse({"error": "Empty message"}, status=400)
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
            },
        )

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
            return JsonResponse({"status": "ok", "message_id": user_msg.id, "model_id": model_id})

        # Non-AJAX fallback (synchronous call)
        try:
            response = AgentRuntimeClient().chat(
                user=request.user,
                session_id=session.external_id,
                prompt=prompt,
                history=serialize_session_history(session),
                conversation_id=conversation_id,
                request_id=request_id,
                origin_channel=session.channel,
                model_id=model_id,
            )
        except AgentRuntimeError as exc:
            append_chat_message(
                session=session,
                role=ChatMessage.Role.SYSTEM,
                content=f"Ошибка agent runtime: {exc}",
                metadata={"conversation_id": conversation_id, "request_id": request_id},
            )
            messages.error(request, "AI runtime недоступен или вернул ошибку.")
            return redirect("ai:chat_detail", external_id=session.external_id)

        tool_trace = response.get("tool_trace", [])
        runtime_conversation_id = response.get("conversation_id") or conversation_id
        runtime_request_id = response.get("request_id") or request_id
        for entry in tool_trace:
            entry["conversation_id"] = runtime_conversation_id
            entry["request_id"] = runtime_request_id
            entry["origin_channel"] = session.channel

        assistant_msg = append_chat_message(
            session=session,
            role=ChatMessage.Role.ASSISTANT,
            content=response["assistant_message"],
            metadata={
                "tool_trace": tool_trace,
                "conversation_id": runtime_conversation_id,
                "request_id": runtime_request_id,
            },
        )

        session.metadata["conversation_id"] = runtime_conversation_id
        if "request_ids" not in session.metadata:
            session.metadata["request_ids"] = []
        session.metadata["request_ids"].append(runtime_request_id)
        session.save(update_fields=["metadata", "updated_at"])

        return redirect("ai:chat_detail", external_id=session.external_id)


class AIChatMessageStreamView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(ChatSession.objects.filter(user=request.user), external_id=external_id)
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)
        msg_id = body.get("msg_id")
        prompt = body.get("prompt", "")
        if len(prompt) > 10000:
            prompt = prompt[:10000]
        model_id = body.get("model_id", "") or session.metadata.get("model_id", "")
        
        conversation_id = session.metadata.get("conversation_id") or str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        # If msg_id is provided, the message was already created by AIChatMessageCreateView
        if msg_id:
            user_msg = get_object_or_404(ChatMessage, id=msg_id, session=session)
            prompt = user_msg.content
        elif prompt:
            # Fallback for older clients that don't use the two-step upload process
            append_chat_message(
                session=session,
                role=ChatMessage.Role.USER,
                content=prompt,
                metadata={
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "origin_channel": session.channel,
                },
            )
        else:
            return JsonResponse({"error": "Prompt or msg_id is required."}, status=400)

        def stream_generator():
            client = AgentRuntimeClient()
            full_content = []
            
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
                ):
                    yield f"{event}\n\n"
                    
                    if event.startswith("data: "):
                        data_str = event[6:]
                        if data_str != "[DONE]":
                            try:
                                data_json = json.loads(data_str)
                                if "content" in data_json:
                                    full_content.append(data_json["content"])
                            except:
                                pass
            except Exception as e:
                logger.error(f"Stream error: {e}", exc_info=True)
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

            if full_content:
                append_chat_message(
                    session=session,
                    role=ChatMessage.Role.ASSISTANT,
                    content="".join(full_content),
                    metadata={
                        "conversation_id": conversation_id,
                        "request_id": request_id,
                        "streamed": True
                    },
                )

        return StreamingHttpResponse(stream_generator(), content_type="text/event-stream")


class AIChatUpdateModelView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(ChatSession.objects.filter(user=request.user), external_id=external_id)
        try:
            body = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)
        model_id = body.get("model_id", "")
        valid_ids = {m["id"] for m in settings.LOCAL_BUSINESS_AI_MODELS}
        if model_id and model_id not in valid_ids:
            return JsonResponse({"error": "Invalid model_id."}, status=400)
        session.metadata["model_id"] = model_id
        session.save(update_fields=["metadata", "updated_at"])
        return JsonResponse({"status": "ok", "model_id": model_id})


class AIChatUpdateTitleView(LoginRequiredMixin, View):
    def post(self, request, external_id):
        session = get_object_or_404(ChatSession.objects.filter(user=request.user), external_id=external_id)
        try:
            body = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)
        title = body.get("title", "").strip()[:255]
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
        session.delete()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"status": "ok"})
        return redirect("ai:chat_index")


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
            return JsonResponse({"error": "Unknown tool."}, status=404)

        if result.get("ok"):
            return JsonResponse(result, status=200)
        return JsonResponse(result, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class AIToolConfirmView(View):
    http_method_names = ["post"]

    def dispatch(self, request, *args, **kwargs):
        expected_token = settings.LOCAL_BUSINESS_AI_GATEWAY_TOKEN
        gateway_token = request.headers.get("X-AI-Gateway-Token", "")
        if not expected_token or gateway_token != expected_token:
            return HttpResponseForbidden("AI gateway token is invalid.")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, token):
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        confirmed = body.get("confirmed", False)
        actor_context = body.get("actor", {})
        session_id = body.get("session_id")
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
        expected_token = settings.LOCAL_BUSINESS_AI_GATEWAY_TOKEN
        gateway_token = request.headers.get("X-AI-Gateway-Token", "")
        if not expected_token or gateway_token != expected_token:
            return HttpResponseForbidden("AI gateway token is invalid.")
        
        from .skills_service import discover_skills
        return JsonResponse({"skills": discover_skills()})

@method_decorator(csrf_exempt, name="dispatch")
class AISkillLoadView(View):
    def get(self, request, skill_id):
        expected_token = settings.LOCAL_BUSINESS_AI_GATEWAY_TOKEN
        gateway_token = request.headers.get("X-AI-Gateway-Token", "")
        if not expected_token or gateway_token != expected_token:
            return HttpResponseForbidden("AI gateway token is invalid.")
        
        from .skills_service import load_skill_content
        content = load_skill_content(skill_id)
        if content:
            return JsonResponse({"id": skill_id, "instructions": content})
        return JsonResponse({"error": "Skill not found"}, status=404)


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
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

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
