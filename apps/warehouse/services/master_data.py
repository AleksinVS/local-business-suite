from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.warehouse.models import (
    FundingSource,
    StockLot,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
    WarehouseAuditEvent,
    WarehouseItem,
    WarehouseItemCategory,
    WarehouseReportProfile,
)
from apps.warehouse.policies import (
    WAREHOUSE_MANAGE_LOCATIONS_SCOPE,
    WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE,
    WAREHOUSE_OPERATE_SCOPE,
    require_warehouse_catalog_access,
    require_warehouse_scope,
)


CATALOG_FIELDS = {
    WarehouseItemCategory: ("code", "name", "is_active"),
    UnitOfMeasure: ("code", "name", "quantity_precision", "is_active"),
    FundingSource: ("code", "name", "is_active"),
    WarehouseItem: (
        "code",
        "name",
        "short_name",
        "category",
        "unit",
        "manufacturer",
        "dosage_form",
        "application_method",
        "is_active",
    ),
}


def _assign(instance, cleaned_data, fields):
    for field in fields:
        if field in cleaned_data:
            setattr(instance, field, cleaned_data[field])


def _audit(*, actor, department, action, instance, summary=None):
    WarehouseAuditEvent.objects.create(
        actor=actor,
        department=department,
        action=action,
        object_type=type(instance).__name__,
        object_id=str(instance.pk),
        summary=summary or {},
    )


@transaction.atomic
def save_warehouse(*, actor, cleaned_data: dict, warehouse_id: int | None = None):
    instance = (
        Warehouse.objects.select_for_update().get(pk=warehouse_id)
        if warehouse_id
        else Warehouse()
    )
    department = cleaned_data.get("department", instance.department if instance.pk else None)
    require_warehouse_scope(
        actor=actor,
        capability=WAREHOUSE_MANAGE_LOCATIONS_SCOPE,
        department=department,
    )
    _assign(instance, cleaned_data, ("department", "code", "name", "is_active"))
    instance.full_clean()
    instance.save()
    _audit(
        actor=actor,
        department=instance.department,
        action="warehouse.saved",
        instance=instance,
        summary={"code": instance.code, "is_active": instance.is_active},
    )
    return instance


@transaction.atomic
def save_storage_location(*, actor, cleaned_data: dict, location_id: int | None = None):
    instance = (
        StorageLocation.objects.select_for_update().select_related("warehouse__department").get(
            pk=location_id
        )
        if location_id
        else StorageLocation()
    )
    warehouse = cleaned_data.get("warehouse", instance.warehouse if instance.pk else None)
    require_warehouse_scope(
        actor=actor,
        capability=WAREHOUSE_MANAGE_LOCATIONS_SCOPE,
        department=warehouse.department,
    )
    _assign(
        instance,
        cleaned_data,
        ("warehouse", "code", "name", "location_type", "purpose", "sort_order", "is_active"),
    )
    instance.full_clean()
    instance.save()
    _audit(
        actor=actor,
        department=instance.warehouse.department,
        action="storage_location.saved",
        instance=instance,
        summary={"code": instance.code, "purpose": instance.purpose},
    )
    return instance


@transaction.atomic
def save_report_profile(*, actor, cleaned_data: dict, profile_id: int | None = None):
    instance = (
        WarehouseReportProfile.objects.select_for_update().select_related("department").get(
            pk=profile_id
        )
        if profile_id
        else WarehouseReportProfile(created_by=actor)
    )
    department = cleaned_data.get("department", instance.department if instance.pk else None)
    require_warehouse_scope(
        actor=actor,
        capability=WAREHOUSE_MANAGE_REPORT_PROFILES_SCOPE,
        department=department,
    )
    _assign(
        instance,
        cleaned_data,
        (
            "department",
            "name",
            "valid_from",
            "valid_to",
            "approval_label",
            "signer_position",
            "signer_name",
            "footer_note",
            "is_active",
        ),
    )
    instance.full_clean()
    instance.save()
    _audit(
        actor=actor,
        department=instance.department,
        action="report_profile.saved",
        instance=instance,
        summary={"name": instance.name, "is_active": instance.is_active},
    )
    return instance


@transaction.atomic
def save_catalog_record(*, actor, model, cleaned_data: dict, object_id: int | None = None):
    fields = CATALOG_FIELDS.get(model)
    if fields is None:
        raise ValidationError("Модель не входит в складской каталог.")
    require_warehouse_catalog_access(actor=actor)
    instance = model.objects.select_for_update().get(pk=object_id) if object_id else model()
    _assign(instance, cleaned_data, fields)
    instance.full_clean()
    instance.save()
    _audit(
        actor=actor,
        department=None,
        action="catalog.saved",
        instance=instance,
        summary={"code": instance.code, "is_active": instance.is_active},
    )
    return instance


@transaction.atomic
def register_stock_lot(*, actor, cleaned_data: dict):
    department = cleaned_data.get("department")
    require_warehouse_scope(
        actor=actor,
        capability=WAREHOUSE_OPERATE_SCOPE,
        department=department,
    )
    instance = StockLot()
    _assign(
        instance,
        cleaned_data,
        ("item", "batch_number", "expires_on", "incomplete_reason"),
    )
    instance.full_clean()
    instance.save()
    _audit(
        actor=actor,
        department=department,
        action="stock_lot.registered",
        instance=instance,
        summary={
            "item_id": instance.item_id,
            "expires_on": instance.expires_on.isoformat()
            if instance.expires_on
            else None,
        },
    )
    return instance
