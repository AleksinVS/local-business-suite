import re
from datetime import date, datetime
from django.db import transaction

from .models import (
    SERVICE_CHOICES,
    WaitingListAuditLog,
    WaitingListEntry,
    WaitingListStatus,
)


_NOT_PROVIDED = object()
_SERVICE_CODES = {code for code, _label in SERVICE_CHOICES}
_AUDIT_FIELD_LABELS = {
    "patient_name": "ФИО пациента",
    "patient_dob": "дата рождения",
    "patient_phone": "телефон",
    "service_id": "услуга",
    "date_tag": "целевая дата",
    "date_end": "крайняя дата",
    "priority_cito": "приоритет CITO",
    "comment": "комментарий",
}


def _phone_valid(phone: str) -> bool:
    """Validate Russian phone format: +7 (XXX) XXX-XX-XX or 8 XXX XXX-XX-XX"""
    cleaned = re.sub(r"[^\d]", "", phone)
    return len(cleaned) == 11 and cleaned.startswith(("7", "8"))


def _parse_dob(dob):
    """Parse DD.MM.YYYY string into a date object."""
    if isinstance(dob, date) and not isinstance(dob, datetime):
        return dob
    match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", dob)
    if match:
        day, month, year = map(int, match.groups())
        return date(year, month, day)
    # Fallback: try ISO format
    try:
        return datetime.strptime(dob, "%Y-%m-%d").date()
    except ValueError:
        return None


def _dob_valid(dob) -> bool:
    """Validate date of birth (string or date)."""
    if isinstance(dob, date) and not isinstance(dob, datetime):
        return True
    if not isinstance(dob, str):
        return False
    return _parse_dob(dob) is not None


class WaitingListValidationError(Exception):
    pass


@transaction.atomic
def create_entry(
    *,
    author,
    patient_name: str,
    patient_dob,
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

    parsed_dob = _parse_dob(patient_dob) if isinstance(patient_dob, str) else patient_dob

    if service_id not in _SERVICE_CODES:
        raise WaitingListValidationError("Выбрана недопустимая услуга.")

    if date_tag and date_end and date_tag > date_end:
        raise WaitingListValidationError("Целевая дата не может быть позже крайней даты.")

    entry = WaitingListEntry.objects.create(
        author=author,
        patient_name=patient_name.strip(),
        patient_dob=parsed_dob,
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


@transaction.atomic
def update_entry(
    *,
    entry: WaitingListEntry,
    user,
    patient_name=_NOT_PROVIDED,
    patient_dob=_NOT_PROVIDED,
    patient_phone=_NOT_PROVIDED,
    service_id=_NOT_PROVIDED,
    date_tag=_NOT_PROVIDED,
    date_end=_NOT_PROVIDED,
    priority_cito=_NOT_PROVIDED,
    comment=_NOT_PROVIDED,
) -> WaitingListEntry:
    """
    Update a waiting list entry with validation.
    Raises WaitingListValidationError on validation failure.
    """
    locked_entry = WaitingListEntry.objects.select_for_update().get(pk=entry.pk)
    normalized_values = {}

    if patient_name is not _NOT_PROVIDED:
        if len(patient_name.strip()) < 2:
            raise WaitingListValidationError("ФИО пациента обязательно (минимум 2 символа).")
        normalized_values["patient_name"] = patient_name.strip()

    if patient_dob is not _NOT_PROVIDED:
        if not _dob_valid(patient_dob):
            raise WaitingListValidationError(
                "Неверный формат даты рождения. Используйте ДД.ММ.ГГГГ."
            )
        normalized_values["patient_dob"] = (
            _parse_dob(patient_dob) if isinstance(patient_dob, str) else patient_dob
        )

    if patient_phone is not _NOT_PROVIDED:
        if not _phone_valid(patient_phone):
            raise WaitingListValidationError(
                "Неверный формат телефона. Используйте +7 (XXX) XXX-XX-XX."
            )
        normalized_values["patient_phone"] = patient_phone

    if service_id is not _NOT_PROVIDED:
        if service_id not in _SERVICE_CODES:
            raise WaitingListValidationError("Выбрана недопустимая услуга.")
        normalized_values["service_id"] = service_id

    if date_tag is not _NOT_PROVIDED:
        normalized_values["date_tag"] = date_tag

    if date_end is not _NOT_PROVIDED:
        normalized_values["date_end"] = date_end

    if priority_cito is not _NOT_PROVIDED:
        normalized_values["priority_cito"] = bool(priority_cito)

    if comment is not _NOT_PROVIDED:
        normalized_values["comment"] = comment or ""

    resulting_date_tag = normalized_values.get("date_tag", locked_entry.date_tag)
    resulting_date_end = normalized_values.get("date_end", locked_entry.date_end)
    if resulting_date_tag and resulting_date_end and resulting_date_tag > resulting_date_end:
        raise WaitingListValidationError("Целевая дата не может быть позже крайней даты.")

    changed_fields = []
    for field_name, new_value in normalized_values.items():
        if getattr(locked_entry, field_name) == new_value:
            continue
        setattr(locked_entry, field_name, new_value)
        changed_fields.append(field_name)

    if not changed_fields:
        return locked_entry

    locked_entry.save(update_fields=[*changed_fields, "updated_at"])
    changed_labels = [_AUDIT_FIELD_LABELS[field_name] for field_name in changed_fields]
    _create_audit_log(
        entry=locked_entry,
        actor=user,
        action=f"Изменены поля: {', '.join(changed_labels)}",
    )

    return locked_entry


@transaction.atomic
def transition_entry(
    *,
    entry: WaitingListEntry,
    user,
    to_status: str,
) -> WaitingListEntry:
    """
    Transition entry to a new status and create audit log.
    """
    locked_entry = WaitingListEntry.objects.select_for_update().get(pk=entry.pk)
    if locked_entry.status == to_status:
        return locked_entry

    locked_entry.status = to_status
    locked_entry.save(
        update_fields=["status", "updated_at"],
    )

    _create_audit_log(
        entry=locked_entry,
        actor=user,
        action=f"Статус изменен на '{ WaitingListStatus(to_status).label }'",
    )

    return locked_entry


def _create_audit_log(*, entry: WaitingListEntry, actor, action: str) -> WaitingListAuditLog:
    """
    Centralized audit log creation - single source of truth for timeline.
    """
    return WaitingListAuditLog.objects.create(
        entry=entry,
        actor=actor,
        action=action,
    )
