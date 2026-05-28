import logging
import os
import re
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.core.models import Department
from apps.inventory.models import MedicalDevice
from apps.workorders.models import Board, WorkOrder, WorkOrderPriority
from apps.workorders.policies import (
    can_comment,
    can_create,
    can_transition,
    can_confirm_closure,
    can_rate,
)
from apps.workorders.selectors import visible_workorders_queryset
from apps.workorders.services import (
    create_workorder,
    transition_workorder,
    confirm_closure,
    rate_workorder,
)

from .models import AgentActionLog, ChatMessage, ChatSession
from .chat_settings import CHAT_SURFACE_SIDEBAR, get_chat_settings, get_recent_message_limit

logger = logging.getLogger(__name__)

AI_SESSION_NAMESPACE = uuid.UUID("4cf98619-f5ff-4f02-9d68-b9240c5778c8")

DEFAULT_CHAT_TITLE = "Новый чат"


def generate_session_title(session):
    """Generate a concise title for a chat session using the configured LLM.

    Sends the first few messages of the conversation to the model with a
    system prompt asking for a short title. Returns the generated title
    string on success, or None if generation fails.
    """
    messages = list(session.messages.order_by("created_at", "id")[:20])
    if not messages:
        return None

    model_config = _resolve_model_config(session.metadata.get("model_id", ""))
    if not model_config:
        return None

    api_key = os.environ.get(model_config.get("api_key_env", ""), "")
    if not api_key:
        logger.warning("generate_session_title: API key %s not set", model_config.get("api_key_env"))
        return None

    model_name = model_config.get("model", "")
    if model_name.startswith("openai:"):
        model_name = model_name[7:]

    chat_messages = [
        {"role": "system", "content": (
            "Проанализируй смысл этого диалога и сгенерируй краткий заголовок, "
            "который отражает основную тему или цель разговора. "
            "Не используй текст последнего сообщения — определи общий контекст. "
            "Заголовок должен содержать строго не более 50 символов. "
            "Если заголовок получается длиннее 50 символов — сократи его. "
            "Ответь только заголовком, без кавычек и пояснений. "
            "Язык заголовка должен соответствовать языку диалога."
        )}
    ]
    for msg in messages:
        role = "user" if msg.role == ChatMessage.Role.USER else "assistant"
        chat_messages.append({"role": role, "content": msg.content[:500]})

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=model_config["base_url"].rstrip("/") + "/")
        response = client.chat.completions.create(
            model=model_name,
            messages=chat_messages,
            max_tokens=60,
            temperature=0.3,
        )
        title = response.choices[0].message.content.strip().strip('"\'')
        if title:
            return title[:50]
    except Exception:
        logger.exception("generate_session_title: LLM call failed")

    return None


def _resolve_model_config(model_id):
    """Find the model config dict matching *model_id*, or the default model."""
    models = getattr(settings, "LOCAL_BUSINESS_AI_MODELS", [])
    if model_id:
        for m in models:
            if m.get("id") == model_id:
                return m
    for m in models:
        if m.get("default"):
            return m
    return models[0] if models else None


def resolve_actor(*, user_id=None, username=None):
    User = get_user_model()
    try:
        if user_id:
            return User.objects.get(pk=user_id)
        if username:
            return User.objects.get(username=username)
    except User.DoesNotExist:
        raise ValidationError("Actor identity not found.")
    raise ValidationError("Actor identity is required.")


def normalize_session_external_id(session_external_id):
    if not session_external_id:
        return None
    if isinstance(session_external_id, uuid.UUID):
        return session_external_id
    try:
        return uuid.UUID(str(session_external_id))
    except (ValueError, TypeError):
        return uuid.uuid5(AI_SESSION_NAMESPACE, str(session_external_id))


def get_or_create_session(
    *, user, session_external_id=None, channel=ChatSession.Channel.INTERNAL, title=""
):
    normalized_external_id = normalize_session_external_id(session_external_id)
    if normalized_external_id:
        session, _ = ChatSession.objects.get_or_create(
            external_id=normalized_external_id,
            user=user,
            defaults={"channel": channel, "title": title},
        )
        return session
    return ChatSession.objects.create(user=user, channel=channel, title=title)


def get_or_create_sidebar_session(user):
    session = (
        ChatSession.objects.filter(
            user=user,
            channel=ChatSession.Channel.SIDEBAR,
            status=ChatSession.Status.ACTIVE,
        )
        .order_by("-updated_at", "-id")
        .first()
    )
    if session:
        return session
    return ChatSession.objects.create(
        user=user,
        channel=ChatSession.Channel.SIDEBAR,
        title="Боковой чат",
        metadata={"surface": CHAT_SURFACE_SIDEBAR},
    )


def append_chat_message(*, session, role, content, tool_name="", metadata=None):
    message = ChatMessage.objects.create(
        session=session,
        role=role,
        content=content,
        tool_name=tool_name,
        metadata=metadata or {},
    )
    session.last_message_at = message.created_at
    session.save(update_fields=["last_message_at", "updated_at"])
    return message


def serialize_session_history(session):
    history = []
    messages_qs = session.messages.prefetch_related("attachments").order_by("created_at", "id")
    if session.channel == ChatSession.Channel.SIDEBAR:
        settings_payload = get_chat_settings(CHAT_SURFACE_SIDEBAR)
        recent_limit = get_recent_message_limit(CHAT_SURFACE_SIDEBAR)
        messages = list(messages_qs)
        sidebar_summary = (session.metadata or {}).get("sidebar_summary") or {}
        if settings_payload.get("summary_enabled", True) and sidebar_summary.get("text"):
            history.append(
                {
                    "role": ChatMessage.Role.SYSTEM,
                    "content": "Краткое резюме предыдущей части sidebar-диалога:\n" + sidebar_summary["text"],
                    "tool_name": "",
                }
            )
        messages_qs = messages[-recent_limit:]
    for message in messages_qs:
        content = message.content
        attachments = list(message.attachments.all())
        if attachments:
            att_info = "\n\n[Прикрепленные файлы: " + ", ".join(f"{a.file_name} ({a.get_file_type_display()})" for a in attachments) + "]"
            content = (content + att_info).strip()

        history.append({
            "role": message.role,
            "content": content,
            "tool_name": message.tool_name,
        })
    return history


def compact_sidebar_session(session):
    if session.channel != ChatSession.Channel.SIDEBAR:
        return False
    settings_payload = get_chat_settings(CHAT_SURFACE_SIDEBAR)
    if not settings_payload.get("summary_enabled", True):
        return False
    recent_limit = get_recent_message_limit(CHAT_SURFACE_SIDEBAR)
    trigger = int(settings_payload.get("summary_trigger_messages") or 24)
    messages = list(session.messages.order_by("created_at", "id"))
    if len(messages) <= recent_limit + trigger:
        return False
    older = messages[:-recent_limit]
    if not older:
        return False
    summary_text = _build_sidebar_summary_text(older)
    session.metadata = {
        **(session.metadata or {}),
        "sidebar_summary": {
            "text": summary_text,
            "summarized_from_message_id": older[0].id,
            "summarized_until_message_id": older[-1].id,
            "source_message_ids": [message.id for message in older],
            "summary_version": "deterministic-v1",
            "summary_updated_at": timezone.now().isoformat(),
        },
    }
    session.save(update_fields=["metadata", "updated_at"])
    return True


def _build_sidebar_summary_text(messages):
    lines = []
    for message in messages[-80:]:
        role = "Пользователь" if message.role == ChatMessage.Role.USER else "Ассистент"
        if message.role == ChatMessage.Role.SYSTEM:
            role = "Система"
        if message.role == ChatMessage.Role.TOOL:
            role = "Инструмент"
        content = mask_chat_runtime_text(message.content)
        if len(content) > 220:
            content = content[:217] + "..."
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)[-6000:]


SECRET_LIKE_RE = re.compile(
    r"(?i)\b(password|passwd|token|api[_-]?key|secret|credential)\b\s*[:=]\s*([^\s,;]+)"
)


def mask_chat_runtime_text(value):
    text = str(value or "")
    text = SECRET_LIKE_RE.sub(lambda match: f"{match.group(1)}=<MASKED>", text)
    return text.strip()


def list_workorders_for_actor(*, actor, status=None, limit=20):
    queryset = visible_workorders_queryset(actor).order_by("-updated_at")
    if status:
        queryset = queryset.filter(status=status)
    items = queryset[:limit]
    return [
        {
            "id": workorder.id,
            "number": workorder.number,
            "title": workorder.title,
            "status": workorder.status,
            "priority": workorder.priority,
            "department": workorder.department.full_name,
            "device": workorder.device.name if workorder.device else None,
            "assignee": workorder.assignee.username if workorder.assignee else None,
            "updated_at": workorder.updated_at.isoformat(),
        }
        for workorder in items
    ]


def get_workorder_for_actor(*, actor, workorder_id=None, number=None):
    queryset = visible_workorders_queryset(actor)
    if workorder_id:
        workorder = queryset.get(pk=workorder_id)
    elif number:
        workorder = queryset.get(number=number)
    else:
        raise ValidationError("workorder_id or number is required.")
    return {
        "id": workorder.id,
        "number": workorder.number,
        "title": workorder.title,
        "description": workorder.description,
        "status": workorder.status,
        "priority": workorder.priority,
        "department": workorder.department.full_name,
        "device": workorder.device.name if workorder.device else None,
        "assignee": workorder.assignee.username if workorder.assignee else None,
        "author": workorder.author.username,
        "updated_at": workorder.updated_at.isoformat(),
    }


def create_workorder_for_actor(*, actor, payload):
    if not can_create(actor):
        raise PermissionDenied("Work order creation is not allowed for this user.")
    department = Department.objects.get(pk=payload["department_id"])
    board = Board.objects.filter(slug="main").first()
    if not board:
        raise ValidationError("Default board 'main' does not exist. Contact administrator.")
    workorder = create_workorder(
        author=actor,
        title=payload.get("title") or payload["subject"],
        description=payload["description"],
        department=department,
        priority=payload.get("priority", WorkOrderPriority.MEDIUM),
        device_id=payload.get("device_id"),
        board=board,
    )
    return {
        "id": workorder.id,
        "number": workorder.number,
        "title": workorder.title,
        "status": workorder.status,
    }


def transition_workorder_for_actor(*, actor, payload):
    workorder = visible_workorders_queryset(actor).get(pk=payload["workorder_id"])
    target_status = payload["target_status"]
    if not can_transition(actor, workorder, target_status):
        raise PermissionDenied("Status transition is not allowed for this user.")
    workorder = transition_workorder(
        workorder=workorder, user=actor, to_status=target_status
    )
    return {
        "id": workorder.id,
        "number": workorder.number,
        "status": workorder.status,
        "updated_at": workorder.updated_at.isoformat(),
    }


def add_comment_for_actor(*, actor, payload):
    workorder = visible_workorders_queryset(actor).get(pk=payload["workorder_id"])
    if not can_comment(actor, workorder):
        raise PermissionDenied("Commenting is not allowed for this user.")
    comment = workorder.comments.create(author=actor, body=payload["text"])
    workorder.updated_at = timezone.now()
    workorder.save(update_fields=["updated_at"])
    return {
        "id": comment.id,
        "workorder_id": workorder.id,
        "body": comment.body,
        "author": actor.username,
        "created_at": comment.created_at.isoformat(),
    }


def list_departments_for_actor(*, actor, query="", parent_id=None):
    if not actor.is_authenticated:
        raise PermissionDenied("Authentication required.")
    queryset = Department.objects.select_related("parent").order_by(
        "parent_id", "name", "id"
    )
    if query:
        queryset = queryset.filter(name__icontains=query)
    if parent_id:
        queryset = queryset.filter(parent_id=parent_id)
    return [
        {
            "id": department.id,
            "name": department.name,
            "full_name": department.full_name,
            "parent_id": department.parent_id,
        }
        for department in queryset[:50]
    ]


def list_devices_for_actor(*, actor, query="", department_id=None, archived=False):
    if not actor.is_authenticated:
        raise PermissionDenied("Authentication required.")
    queryset = MedicalDevice.objects.select_related("department").order_by("name", "id")
    if not archived:
        queryset = queryset.filter(is_archived=False)
    if query:
        queryset = queryset.filter(name__icontains=query)
    if department_id:
        queryset = queryset.filter(department_id=department_id)
    return [
        {
            "id": device.id,
            "name": device.name,
            "department": device.department.full_name,
            "model": device.model,
            "serial_number": device.serial_number,
        }
        for device in queryset[:50]
    ]


def record_action(
    *,
    actor,
    tool_code,
    action_kind,
    status,
    request_payload,
    response_payload=None,
    session=None,
    message=None,
    error_message="",
):
    return AgentActionLog.objects.create(
        actor=actor,
        tool_code=tool_code,
        action_kind=action_kind,
        status=status,
        request_payload=request_payload,
        response_payload=response_payload or {},
        session=session,
        message=message,
        error_message=error_message,
    )


def confirm_closure_for_actor(*, actor, payload):
    workorder = visible_workorders_queryset(actor).get(pk=payload["workorder_id"])
    if not can_confirm_closure(actor, workorder):
        raise PermissionDenied("Closure confirmation is not allowed for this user.")
    workorder = confirm_closure(workorder=workorder, user=actor)
    return {
        "id": workorder.id,
        "number": workorder.number,
        "status": workorder.status,
        "closure_confirmed": workorder.closure_confirmed,
        "updated_at": workorder.updated_at.isoformat(),
    }


def rate_workorder_for_actor(*, actor, payload):
    workorder = visible_workorders_queryset(actor).get(pk=payload["workorder_id"])
    if not can_rate(actor, workorder):
        raise PermissionDenied("Rating is not allowed for this user.")
    rating = payload.get("rating")
    if not isinstance(rating, int) or rating < 1 or rating > 5:
        raise ValidationError("Rating must be an integer between 1 and 5.")
    workorder = rate_workorder(
        workorder=workorder, user=actor, rating=rating
    )
    return {
        "id": workorder.id,
        "number": workorder.number,
        "rating": workorder.rating,
        "updated_at": workorder.updated_at.isoformat(),
    }


def create_device_for_actor(*, actor, payload):
    from apps.workorders.policies import can_manage_inventory

    if not can_manage_inventory(actor):
        raise PermissionDenied("Inventory management is not allowed for this user.")
    department = Department.objects.get(pk=payload["department_id"])
    device = MedicalDevice.objects.create(
        name=payload["name"],
        department=department,
        model=payload.get("model", ""),
        serial_number=payload.get("serial_number", ""),
    )
    return {
        "id": device.id,
        "name": device.name,
        "department_id": device.department_id,
    }


def update_device_for_actor(*, actor, payload):
    from apps.workorders.policies import can_manage_inventory

    if not can_manage_inventory(actor):
        raise PermissionDenied("Inventory management is not allowed for this user.")
    device = MedicalDevice.objects.get(pk=payload["device_id"])
    if "name" in payload:
        device.name = payload["name"]
    if "department_id" in payload:
        device.department_id = payload["department_id"]
    if "model" in payload:
        device.model = payload["model"]
    if "serial_number" in payload:
        device.serial_number = payload["serial_number"]
    device.save()
    return {
        "id": device.id,
        "name": device.name,
        "department_id": device.department_id,
    }


def archive_device_for_actor(*, actor, payload):
    from apps.workorders.policies import can_manage_inventory

    if not can_manage_inventory(actor):
        raise PermissionDenied("Inventory management is not allowed for this user.")
    device = MedicalDevice.objects.get(pk=payload["device_id"])
    device.archive()
    return {
        "id": device.id,
        "is_archived": device.is_archived,
    }


def get_analytics_summary_for_actor(*, actor, payload):
    from apps.workorders.policies import can_view_analytics
    from django.db.models import Count

    if not can_view_analytics(actor):
        raise PermissionDenied("Analytics access is not allowed for this user.")

    summary_type = payload.get("summary_type")
    base_qs = visible_workorders_queryset(actor).select_related(
        "assignee", "department"
    )

    if summary_type == "status":
        return {
            "summary": list(
                base_qs.values("status").annotate(total=Count("id")).order_by("status")
            )
        }
    elif summary_type == "departments":
        department_rows = list(
            base_qs.values("department")
            .annotate(total=Count("id"))
            .order_by("-total", "department")
        )
        departments = Department.objects.select_related("parent")
        department_map = {d.id: d for d in departments}
        return {
            "summary": [
                {
                    "department_label": department_map[row["department"]].full_name,
                    "total": row["total"],
                }
                for row in department_rows
                if row["department"] in department_map
            ]
        }
    elif summary_type == "assignees":
        return {
            "summary": list(
                base_qs.values(
                    "assignee__username", "assignee__first_name", "assignee__last_name"
                )
                .annotate(total=Count("id"))
                .order_by("-total")
            )
        }
    else:
        raise ValidationError(f"Invalid summary_type: {summary_type}")

def update_role_permissions_for_actor(*, actor, payload):
    """
    Updates permissions for a specific role in config/role_rules.json.
    STRICT SECURITY GATE: Only superusers can perform this action.
    """
    if not actor.is_superuser:
        raise PermissionDenied("CRITICAL: Only administrators with full rights can modify role permissions.")

    from django.conf import settings
    import json
    from apps.core.json_utils import pretty_json, atomic_write_json

    role_name = payload.get("role_name")
    permissions_map = payload.get("permissions_map", {})

    if not role_name:
        raise ValidationError("role_name is required.")

    current_rules = settings.LOCAL_BUSINESS_ROLE_RULES.copy()
    if role_name not in current_rules:
        raise ValidationError(f"Role '{role_name}' does not exist.")

    # Update permissions
    for key, value in permissions_map.items():
        if key in current_rules[role_name] or key == "display_name":
            current_rules[role_name][key] = value

    # Save to file
    atomic_write_json(settings.LOCAL_BUSINESS_ROLE_RULES_FILE, current_rules)
    settings.LOCAL_BUSINESS_ROLE_RULES = current_rules

    return {
        "ok": True,
        "message": f"Permissions for role '{role_name}' updated successfully.",
        "role_name": role_name,
        "updated_keys": list(permissions_map.keys())
    }

def get_role_rules_for_actor(*, actor, payload):
    """Returns the current role configuration from role_rules.json."""
    if not actor.is_authenticated:
        raise PermissionDenied("Authentication required.")
    from django.conf import settings
    return {"rules": settings.LOCAL_BUSINESS_ROLE_RULES}

def list_users_for_actor(*, actor, payload):
    """Lists users with their roles and departments. Only for superusers."""
    if not actor.is_superuser:
        raise PermissionDenied("Only administrators can list all users.")

    User = get_user_model()
    query = payload.get("query", "")
    queryset = User.objects.select_related("department").prefetch_related("groups").all()

    if query:
        queryset = queryset.filter(username__icontains=query) | queryset.filter(first_name__icontains=query) | queryset.filter(last_name__icontains=query)

    return {
        "items": [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.get_full_name(),
                "email": u.email,
                "is_active": u.is_active,
                "is_superuser": u.is_superuser,
                "department": u.department.name if u.department else None,
                "groups": list(u.groups.values_list("name", flat=True))
            }
            for u in queryset[:50]
        ]
    }

def update_user_for_actor(*, actor, payload):
    """Updates user details. Only for superusers."""
    if not actor.is_superuser:
        raise PermissionDenied("Only administrators can update user data.")

    User = get_user_model()
    user_id = payload.get("user_id")
    if not user_id:
        raise ValidationError("user_id is required.")

    target_user = User.objects.get(pk=user_id)

    if "is_active" in payload:
        target_user.is_active = payload["is_active"]

    if "department_id" in payload:
        target_user.department_id = payload["department_id"]

    if "group_names" in payload:
        from django.contrib.auth.models import Group
        groups = Group.objects.filter(name__in=payload["group_names"])
        target_user.groups.set(groups)

    target_user.save()

    return {
        "ok": True,
        "user": {
            "id": target_user.id,
            "username": target_user.username,
            "is_active": target_user.is_active,
            "groups": list(target_user.groups.values_list("name", flat=True))
        }
    }

def list_groups_for_actor(*, actor, payload):
    """Lists all available Django groups. Only for superusers."""
    if not actor.is_superuser:
        raise PermissionDenied("Only administrators can list groups.")
    from django.contrib.auth.models import Group
    return {"items": list(Group.objects.values_list("name", flat=True))}
