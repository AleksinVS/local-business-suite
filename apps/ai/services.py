import logging
import os
import re
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.utils import timezone

from apps.workorders.models import WorkOrder, WorkOrderPriority
from apps.workorders.policies import role_rules
from apps.workorders.selectors import (
    resolve_active_actor,
    visible_workorders_queryset,
)
from apps.inventory.selectors import (
    visible_departments_queryset,
    visible_devices_queryset,
)
from apps.workorders.services import (
    add_workorder_comment_command,
    confirm_workorder_closure_command,
    create_workorder_command,
    rate_workorder_command,
    transition_workorder_command,
)
from apps.inventory.services import (
    archive_device_command,
    create_device_command,
    update_device_command,
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
            actor = User.objects.get(pk=user_id)
        elif username:
            actor = User.objects.get(username=username)
        else:
            raise ValidationError("Учетная запись исполнителя обязательна.")
    except User.DoesNotExist:
        raise ValidationError("Учетная запись исполнителя не найдена.")
    if not actor.is_active:
        raise PermissionDenied("Учетная запись исполнителя отключена.")
    return actor


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


def create_new_sidebar_session(user):
    previous = (
        ChatSession.objects.filter(
            user=user,
            channel=ChatSession.Channel.SIDEBAR,
            status=ChatSession.Status.ACTIVE,
        )
        .order_by("-updated_at", "-id")
        .first()
    )
    metadata = {"surface": CHAT_SURFACE_SIDEBAR}
    if previous:
        previous_metadata = previous.metadata or {}
        model_id = previous_metadata.get("model_id")
        if model_id:
            metadata["model_id"] = model_id
        metadata["previous_sidebar_session_id"] = str(previous.external_id)
        ChatSession.objects.filter(
            user=user,
            channel=ChatSession.Channel.SIDEBAR,
            status=ChatSession.Status.ACTIVE,
        ).update(status=ChatSession.Status.ARCHIVED)
    return ChatSession.objects.create(
        user=user,
        channel=ChatSession.Channel.SIDEBAR,
        title="Боковой чат",
        metadata=metadata,
    )


def clear_sidebar_session(session):
    if session.channel != ChatSession.Channel.SIDEBAR:
        raise ValidationError("Очистка доступна только для бокового чата.")
    session.messages.all().delete()
    session.metadata = {
        key: value
        for key, value in (session.metadata or {}).items()
        if key != "sidebar_summary"
    }
    session.last_message_at = None
    session.save(update_fields=["metadata", "last_message_at", "updated_at"])
    return session


def archive_chat_session(session, *, reason="user_deleted"):
    metadata = {
        **(session.metadata or {}),
        "archive_reason": reason,
        "archived_at": timezone.now().isoformat(),
    }
    session.status = ChatSession.Status.ARCHIVED
    session.metadata = metadata
    session.save(update_fields=["status", "metadata", "updated_at"])
    return session


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
        # TOOL и SYSTEM сообщения — служебные; в пользовательском summary они
        # не нужны (TOOL-сообщения пользователь всё равно не видит в UI,
        # SYSTEM — это синтетические вставки для LLM-контекста).
        if message.role in (ChatMessage.Role.SYSTEM, ChatMessage.Role.TOOL):
            continue
        role = "Пользователь" if message.role == ChatMessage.Role.USER else "Ассистент"
        content = mask_chat_runtime_text(message.content)
        if len(content) > 220:
            content = content[:217] + "..."
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)[-6000:]


SECRET_LIKE_RE = re.compile(
    r"(?i)\b(password|passwd|token|api[_-]?key|secret|credential)\b\s*[:=]\s*([^\s,;]+)"
)
AI_AUDIT_PII_KEYS = {
    "username",
    "email",
    "full_name",
    "first_name",
    "last_name",
    "author",
    "assignee",
    "upn",
    "subject_id",
    "distinguished_name",
}


def mask_chat_runtime_text(value):
    text = str(value or "")
    text = SECRET_LIKE_RE.sub(lambda match: f"{match.group(1)}=<MASKED>", text)
    return text.strip()


def list_workorders_for_actor(*, actor, status=None, limit=20):
    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None:
        return []
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
    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None:
        raise PermissionDenied("Требуется активная учетная запись.")
    queryset = visible_workorders_queryset(actor)
    try:
        if workorder_id:
            workorder = queryset.get(pk=workorder_id)
        elif number:
            workorder = queryset.get(number=number)
        else:
            raise ValidationError("Нужно указать workorder_id или number.")
    except WorkOrder.DoesNotExist as exc:
        raise PermissionDenied("Заявка недоступна текущему пользователю.") from exc
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


def get_waiting_list_entry_for_actor(*, actor, entry_id=None):
    from apps.waiting_list.selectors import visible_waiting_list_entries

    if not entry_id:
        raise ValidationError("Нужно указать entry_id.")
    current_actor = get_user_model().objects.filter(
        pk=getattr(actor, "pk", None),
        is_active=True,
    ).first()
    if current_actor is None:
        raise PermissionDenied("Пользователю недоступен лист ожидания.")
    rules_payload = role_rules()
    try:
        entry = visible_waiting_list_entries(
            current_actor, rules_payload=rules_payload
        ).get(pk=entry_id)
    except ObjectDoesNotExist as exc:
        raise PermissionDenied("Запись листа ожидания недоступна текущему пользователю.") from exc
    return {
        "id": entry.id,
        "status": entry.status,
        "service_id": entry.service_id,
        "service": entry.get_service_id_display(),
        "priority_cito": entry.priority_cito,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def create_workorder_for_actor(*, actor, payload):
    workorder = create_workorder_command(
        actor=actor,
        payload={
            "title": payload.get("title") or payload["subject"],
            "description": payload["description"],
            "department_id": payload["department_id"],
            "priority": payload.get("priority", WorkOrderPriority.MEDIUM),
            "device_id": payload.get("device_id"),
        },
    )
    return {
        "id": workorder.id,
        "number": workorder.number,
        "title": workorder.title,
        "status": workorder.status,
    }


def transition_workorder_for_actor(*, actor, payload):
    workorder = transition_workorder_command(
        actor=actor,
        workorder_id=payload["workorder_id"],
        target_status=payload["target_status"],
    )
    return {
        "id": workorder.id,
        "number": workorder.number,
        "status": workorder.status,
        "updated_at": workorder.updated_at.isoformat(),
    }


def add_comment_for_actor(*, actor, payload):
    comment = add_workorder_comment_command(
        actor=actor,
        workorder_id=payload["workorder_id"],
        body=payload["text"],
    )
    return {
        "id": comment.id,
        "workorder_id": comment.workorder_id,
        "body": comment.body,
        "author": comment.author.username,
        "created_at": comment.created_at.isoformat(),
    }


def list_departments_for_actor(*, actor, query="", parent_id=None):
    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None:
        return []
    queryset = visible_departments_queryset(actor)
    if query:
        queryset = queryset.filter(name__icontains=query)
    if parent_id:
        if not queryset.filter(pk=parent_id).exists():
            return []
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
    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None:
        return []
    queryset = visible_devices_queryset(actor, include_archived=bool(archived))
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
        request_payload=_sanitize_ai_audit_payload(request_payload),
        response_payload=_sanitize_ai_audit_payload(response_payload or {}),
        session=session,
        message=message,
        error_message=error_message,
    )


def _sanitize_ai_audit_payload(value):
    """Удалить identity PII из долговечного AI-аудита, сохранив структуру."""
    if isinstance(value, dict):
        return {
            key: (
                "***"
                if str(key).casefold() in AI_AUDIT_PII_KEYS and item not in (None, "")
                else _sanitize_ai_audit_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_ai_audit_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_ai_audit_payload(item) for item in value]
    return value


def confirm_closure_for_actor(*, actor, payload):
    workorder = confirm_workorder_closure_command(
        actor=actor,
        workorder_id=payload["workorder_id"],
    )
    return {
        "id": workorder.id,
        "number": workorder.number,
        "status": workorder.status,
        "closure_confirmed": workorder.closure_confirmed,
        "updated_at": workorder.updated_at.isoformat(),
    }


def rate_workorder_for_actor(*, actor, payload):
    workorder = rate_workorder_command(
        actor=actor,
        workorder_id=payload["workorder_id"],
        rating=payload.get("rating"),
    )
    return {
        "id": workorder.id,
        "number": workorder.number,
        "rating": workorder.rating,
        "updated_at": workorder.updated_at.isoformat(),
    }


def create_device_for_actor(*, actor, payload):
    device = create_device_command(
        actor=actor,
        payload={
            "name": payload["name"],
            "department": payload["department_id"],
            "model": payload.get("model", ""),
            "serial_number": payload.get("serial_number", ""),
        },
    )
    return {
        "id": device.id,
        "name": device.name,
        "department_id": device.department_id,
    }


def update_device_for_actor(*, actor, payload):
    update_payload = {
        key: payload[key]
        for key in ("name", "model", "serial_number")
        if key in payload
    }
    if "department_id" in payload:
        update_payload["department"] = payload["department_id"]
    device = update_device_command(
        actor=actor,
        device_id=payload["device_id"],
        payload=update_payload,
    )
    return {
        "id": device.id,
        "name": device.name,
        "department_id": device.department_id,
    }


def archive_device_for_actor(*, actor, payload):
    device = archive_device_command(actor=actor, device_id=payload["device_id"])
    return {
        "id": device.id,
        "is_archived": device.is_archived,
    }


def get_analytics_summary_for_actor(*, actor, payload):
    from apps.workorders.policies import can_view_analytics
    from django.db.models import Count

    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None:
        raise PermissionDenied("Требуется активная учетная запись.")
    if not can_view_analytics(actor):
        raise PermissionDenied("Пользователю недоступна аналитика.")

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
        departments = visible_departments_queryset(actor)
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
        raise ValidationError(f"Некорректный summary_type: {summary_type}")


def get_role_rules_for_actor(*, actor, payload):
    """Return role rules only to the product access-administration roles."""
    from apps.accounts.access_contracts import can_edit_role_definitions
    from apps.core.contract_store import get_contract

    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None:
        raise PermissionDenied("Требуется активная учетная запись.")
    from apps.workorders.policies import can_manage_roles

    if not (can_manage_roles(actor) or can_edit_role_definitions(actor)):
        raise PermissionDenied("Правила ролей доступны только администраторам доступа.")
    return {"rules": get_contract("role_rules")}

def list_users_for_actor(*, actor, payload):
    """List privacy-safe access facts for the access administration UI."""
    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None or not actor.is_superuser:
        raise PermissionDenied("Список всех пользователей доступен только администраторам.")

    User = get_user_model()
    query = str(payload.get("query", "") or "").strip()
    queryset = User.objects.select_related("department").prefetch_related("groups__profile").all()

    if query:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )

    from apps.accounts.selectors import split_user_groups

    items = []
    for user in queryset.order_by("username", "pk")[:50]:
        roles, technical = split_user_groups(user)
        memory_names = set()
        from apps.memory.policies import MEMORY_REVIEW_GROUP_CAPABILITIES

        memory_names.update(MEMORY_REVIEW_GROUP_CAPABILITIES)
        technical_names = sorted(group.name for group in technical if group.name not in memory_names)
        memory_group_names = sorted(group.name for group in technical if group.name in memory_names)
        items.append(
            {
                "id": user.id,
                "username": user.username,
                "full_name": user.get_full_name(),
                "is_active": bool(user.is_active),
                "department": user.department.name if user.department else None,
                "roles": sorted(group.name for group in roles),
                "technical_groups": technical_names,
                "memory_groups": memory_group_names,
                "superuser_reserve": bool(user.is_superuser),
                "effective": bool(user.is_active),
            }
        )

    return {"items": items}


def _require_access_explain_authority(actor):
    """Require a fresh manage_roles authority or active superuser reserve."""
    actor = resolve_active_actor(actor, force_refresh=True)
    from apps.workorders.policies import can_manage_roles

    if actor is None or not (actor.is_superuser or can_manage_roles(actor)):
        raise PermissionDenied("Пояснение доступа доступно только администраторам доступа.")
    return actor


def explain_user_access_for_actor(*, actor, payload):
    """Return a minimal explanation made solely from enforcement inputs."""
    actor = _require_access_explain_authority(actor)
    try:
        user_id = int(str(payload.get("user_id", "")).strip())
    except (TypeError, ValueError):
        raise ValidationError("Нужен корректный идентификатор пользователя.")
    user = get_user_model().objects.select_related("department").prefetch_related("groups__profile").filter(pk=user_id).first()
    if user is None:
        raise ValidationError("Пользователь не найден.")
    from apps.accounts.selectors import effective_access_for_user, split_user_groups
    from apps.memory.policies import MEMORY_REVIEW_GROUP_CAPABILITIES

    roles, technical = split_user_groups(user)
    memory_names = set(MEMORY_REVIEW_GROUP_CAPABILITIES)
    explanation = effective_access_for_user(user)
    return {
        "user": {
            "id": user.pk,
            "username": user.username,
            "full_name": user.get_full_name(),
            "department": user.department.name if user.department else None,
            "is_active": bool(user.is_active),
        },
        "assigned": {
            "roles": sorted(group.name for group in roles),
            "technical_groups": sorted(group.name for group in technical if group.name not in memory_names),
            "memory_groups": sorted(group.name for group in technical if group.name in memory_names),
            "superuser_reserve": bool(user.is_superuser),
        },
        "effective": explanation,
        "notes": [
            "Назначенные группы памяти являются отдельным техническим источником.",
            "ACL ресурсов и workflow только сужают доступ и не являются источниками грантов.",
        ],
    }


def open_access_editor_for_actor(*, actor, payload):
    """Build a server-owned, read-only command for the human access editor."""
    actor = _require_access_explain_authority(actor)
    target_type = str(payload.get("target_type", "") or "").strip()
    target_id = str(payload.get("target_id", "") or "").strip()
    if target_type not in {"user", "role"} or not target_id:
        raise ValidationError("Редактор доступа принимает только target_type user|role и target_id.")
    from apps.core.right_panels import build_right_panel_descriptor

    descriptor = build_right_panel_descriptor(
        user=actor,
        source_code="settings_center",
        object_type=target_type,
        object_id=target_id,
        mode="edit",
    )
    return {
        "status": "ok",
        "message": "Команда открытия редактора доступа готова.",
        "ui_command": descriptor.as_dict(),
    }


def list_groups_for_actor(*, actor, payload):
    """Lists all available Django groups. Only for superusers."""
    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None or not actor.is_superuser:
        raise PermissionDenied("Список групп доступен только администраторам.")
    from django.contrib.auth.models import Group
    return {"items": list(Group.objects.values_list("name", flat=True))}
