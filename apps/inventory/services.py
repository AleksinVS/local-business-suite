"""Actor-aware mutation commands for the inventory domain."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.core.models import Department
from apps.workorders.policies import can_manage_inventory
from apps.workorders.selectors import creation_departments_queryset

from .models import MedicalDevice
from .selectors import visible_devices_queryset


DEVICE_MUTABLE_FIELDS = (
    "name",
    "device_type",
    "manufacturer",
    "production_country",
    "model",
    "serial_number",
    "inventory_number",
    "registration_date",
    "registration_certificate_number",
    "production_date",
    "commissioned_at",
    "service_life_years",
    "department",
    "address",
    "location",
    "operational_status",
    "decommissioned_at",
    "decommission_reason",
    "notes",
)


def _lock_actor(actor):
    user = get_user_model().objects.select_for_update().filter(
        pk=getattr(actor, "pk", None), is_active=True
    ).first()
    if user is None:
        raise PermissionDenied("Учетная запись исполнителя отключена или не найдена.")
    return user


def _pk(value):
    return getattr(value, "pk", value)


def _creation_department(actor, value):
    department_id = creation_departments_queryset(actor).filter(
        pk=_pk(value)
    ).values_list("pk", flat=True).first()
    if department_id is None:
        raise PermissionDenied("Недоступно выбранное подразделение.")
    department = Department.objects.select_for_update().filter(pk=department_id).first()
    if department is None or not creation_departments_queryset(actor).filter(
        pk=department.pk
    ).exists():
        raise PermissionDenied("Подразделение стало недоступно.")
    return department


def create_device_command(*, actor, payload):
    unknown = set(payload) - set(DEVICE_MUTABLE_FIELDS)
    if unknown:
        raise ValidationError("Недопустимые поля изделия: " + ", ".join(sorted(unknown)))
    with transaction.atomic():
        current_actor = _lock_actor(actor)
        if not can_manage_inventory(current_actor):
            raise PermissionDenied("Пользователю недоступно управление инвентарем.")
        values = dict(payload)
        values["department"] = _creation_department(current_actor, values.get("department"))
        device = MedicalDevice.objects.create(**values)
    return device


def _locked_visible_device(current_actor, device_id):
    # Lock the base row first, then re-check the actor-scoped selector.  This
    # prevents a stale pre-lock visibility decision from authorizing a write.
    device = MedicalDevice.objects.select_for_update().filter(pk=device_id).first()
    if device is None:
        raise PermissionDenied("Недоступно выбранное медицинское изделие.")
    if not visible_devices_queryset(
        current_actor,
        include_archived=True,
    ).filter(pk=device.pk).values_list("pk", flat=True).first():
        raise PermissionDenied("Недоступно выбранное медицинское изделие.")
    return device


def update_device_command(*, actor, device_id, payload):
    unknown = set(payload) - set(DEVICE_MUTABLE_FIELDS)
    if unknown:
        raise ValidationError("Недопустимые поля изделия: " + ", ".join(sorted(unknown)))
    with transaction.atomic():
        current_actor = _lock_actor(actor)
        if not can_manage_inventory(current_actor):
            raise PermissionDenied("Пользователю недоступно управление инвентарем.")
        values = dict(payload)
        # Inventory mutation follows the shared order: actor -> departments
        # (sorted) -> devices.  Resolve/lock the new department before the
        # device row; authorization is repeated after both locks.
        existing_department_id = MedicalDevice.objects.filter(pk=device_id).values_list(
            "department_id", flat=True
        ).first()
        if "department" in values and _pk(values["department"]) != existing_department_id:
            values["department"] = _creation_department(current_actor, values["department"])
        elif "department" in values:
            values.pop("department")
        device = _locked_visible_device(current_actor, device_id)
        if "department" in values and _pk(values["department"]) == device.department_id:
            values.pop("department")
        for field, value in values.items():
            setattr(device, field, value)
        if values:
            device.save(update_fields=list(values) + ["updated_at"])
    return device


def archive_device_command(*, actor, device_id):
    with transaction.atomic():
        current_actor = _lock_actor(actor)
        if not can_manage_inventory(current_actor):
            raise PermissionDenied("Пользователю недоступно управление инвентарем.")
        device = _locked_visible_device(current_actor, device_id)
        device.archive()
    return device
