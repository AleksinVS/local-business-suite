import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.core.models import Department
from apps.inventory.models import MedicalDevice
from apps.workorders.models import WorkOrder, WorkOrderPriority
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


AI_SESSION_NAMESPACE = uuid.UUID("4cf98619-f5ff-4f02-9d68-b9240c5778c8")


def resolve_actor(*, user_id=None, username=None):
    User = get_user_model()
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
        {
            "role": message.role,
            "content": message.content,
            "tool_name": message.tool_name,
        }
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
    workorder = rate_workorder(
        workorder=workorder, user=actor, rating=payload["rating"]
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
    from apps.workorders.policies import can_manage_inventory
    from django.db.models import Count

    if not can_manage_inventory(actor):
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
    from apps.core.json_utils import pretty_json

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
    settings.LOCAL_BUSINESS_ROLE_RULES_FILE.write_text(pretty_json(current_rules) + "\n", encoding="utf-8")
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
    queryset = User.objects.select_related("department", "organizational_unit").prefetch_related("groups").all()
    
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
