import re
from typing import Optional

from django.db import transaction
from django.utils import timezone

from .models import WaitingListAuditLog, WaitingListEntry, WaitingListStatus


def _phone_valid(phone: str) -> bool:
    """Validate Russian phone format: +7 (XXX) XXX-XX-XX or 8 XXX XXX-XX-XX"""
    cleaned = re.sub(r"[^\d]", "", phone)
    return len(cleaned) == 11 and cleaned.startswith(("7", "8"))


def _dob_valid(dob: str) -> bool:
    """Validate DD.MM.YYYY date format"""
    pattern = r"^\d{2}\.\d{2}\.\d{4}$"
    return bool(re.match(pattern, dob))


class WaitingListValidationError(Exception):
    pass


def create_entry(
    *,
    author,
    patient_name: str,
    patient_dob: str,
    patient_phone: str,
    service_id: str,
    date_tag=None,
    date_end=None,
    priority_cito: bool = False,
    comment: str = "",
) -> WaitingListEntry:
    """
    Create a new waiting list entry with server-side validation.
    Raises WaitingListValidationError on validation failure.
    """
    # Server-side validation
    if not patient_name or len(patient_name.strip()) < 2:
        raise WaitingListValidationError("ФИО пациента обязательно (минимум 2 символа).")

    if not _dob_valid(patient_dob):
        raise WaitingListValidationError("Неверный формат даты рождения. Используйте ДД.ММ.ГГГГ.")

    if not _phone_valid(patient_phone):
        raise WaitingListValidationError(
            "Неверный формат телефона. Используйте +7 (XXX) XXX-XX-XX."
        )

    entry = WaitingListEntry.objects.create(
        patient_name=patient_name.strip(),
        patient_dob=patient_dob,
        patient_phone=patient_phone,
        service_id=service_id,
        date_tag=date_tag,
        date_end=date_end,
        priority_cito=priority_cito,
        comment=comment,
    )

    # Create audit log entry
    _create_audit_log(
        entry=entry,
        actor=author,
        action="Запись создана",
    )

    return entry


def update_entry(
    *,
    entry: WaitingListEntry,
    user,
    patient_name: Optional[str] = None,
    patient_dob: Optional[str] = None,
    patient_phone: Optional[str] = None,
    service_id: Optional[str] = None,
    date_tag=None,
    date_end=None,
    priority_cito: Optional[bool] = None,
    comment: Optional[str] = None,
) -> WaitingListEntry:
    """
    Update a waiting list entry with validation.
    Raises WaitingListValidationError on validation failure.
    """
    changes = []

    if patient_name is not None:
        if len(patient_name.strip()) < 2:
            raise WaitingListValidationError("ФИО пациента обязательно (минимум 2 символа).")
        entry.patient_name = patient_name.strip()
        changes.append("обновлено ФИО")

    if patient_dob is not None:
        if not _dob_valid(patient_dob):
            raise WaitingListValidationError(
                "Неверный формат даты рождения. Используйте ДД.ММ.ГГГГ."
            )
        entry.patient_dob = patient_dob
        changes.append("обновлена дата рождения")

    if patient_phone is not None:
        if not _phone_valid(patient_phone):
            raise WaitingListValidationError(
                "Неверный формат телефона. Используйте +7 (XXX) XXX-XX-XX."
            )
        entry.patient_phone = patient_phone
        changes.append("обновлен телефон")

    if service_id is not None:
        entry.service_id = service_id
        changes.append("обновлена услуга")

    if date_tag is not None:
        entry.date_tag = date_tag
        changes.append("обновлена целевая дата")

    if date_end is not None:
        entry.date_end = date_end
        changes.append("обновлена крайняя дата")

    if priority_cito is not None:
        entry.priority_cito = priority_cito
        changes.append("обновлен приоритет CITO")

    if comment is not None:
        entry.comment = comment
        changes.append("обновлен комментарий")

    entry.save()

    if changes:
        _create_audit_log(
            entry=entry,
            actor=user,
            action=f"Данные записи обновлены: {', '.join(changes)}",
        )

    return entry


def transition_entry(
    *,
    entry: WaitingListEntry,
    user,
    to_status: str,
) -> WaitingListEntry:
    """
    Transition entry to a new status and create audit log.
    """
    previous_status = entry.status
    entry.status = to_status
    entry.save(
        update_fields=["status", "updated_at"],
    )

    _create_audit_log(
        entry=entry,
        actor=user,
        action=f"Статус изменен на '{ WaitingListStatus(to_status).label }'",
    )

    return entry


def _create_audit_log(*, entry: WaitingListEntry, actor, action: str) -> WaitingListAuditLog:
    """
    Centralized audit log creation - single source of truth for timeline.
    """
    return WaitingListAuditLog.objects.create(
        entry=entry,
        actor=actor,
        action=action,
    )
