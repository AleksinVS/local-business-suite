import uuid

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.core.models import Department
from apps.inventory.models import MedicalDevice
from apps.workorders.models import WorkOrder, WorkOrderPriority
from apps.workorders.policies import can_comment, can_create, can_transition
from apps.workorders.selectors import visible_workorders_queryset
from apps.workorders.services import create_workorder, transition_workorder

from .models import AgentActionLog, ChatMessage, ChatSession


AI_SESSION_NAMESPACE = uuid.UUID("4cf98619-f5ff-4f02-9d68-b9240c5778c8")


def resolve_actor(*, user_id=None, username=None):
    if user_id:
        return User.objects.get(pk=user_id)
    if username:
        return User.objects.get(username=username)
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


def get_or_create_session(*, user, session_external_id=None, channel=ChatSession.Channel.INTERNAL, title=""):
    normalized_external_id = normalize_session_external_id(session_external_id)
    if normalized_external_id:
        session, _ = ChatSession.objects.get_or_create(
            external_id=normalized_external_id,
            user=user,
            defaults={"channel": channel, "title": title},
        )
        return session
    return ChatSession.objects.create(user=user, channel=channel, title=title)


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
    return [
        {"role": message.role, "content": message.content, "tool_name": message.tool_name}
        for message in session.messages.order_by("created_at", "id")
    ]


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
    workorder = create_workorder(
        author=actor,
        title=payload.get("title") or payload["subject"],
        description=payload["description"],
        department=department,
        priority=payload.get("priority", WorkOrderPriority.MEDIUM),
        device_id=payload.get("device_id"),
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
    workorder = transition_workorder(workorder=workorder, user=actor, to_status=target_status)
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
    queryset = Department.objects.select_related("parent").order_by("parent_id", "name", "id")
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
