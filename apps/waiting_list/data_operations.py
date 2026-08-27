"""Проверяемые операции импорта данных листа ожидания."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    SERVICE_CHOICES,
    WaitingListAuditLog,
    WaitingListEntry,
    WaitingListStatus,
)

WAITING_LIST_EXPORT_HEADERS = (
    "Услуга",
    "ФИО",
    "Дата рождения",
    "Телефон",
    "Дата записи",
    "История изменений",
    "Дата бирки",
    "Дата окончания",
    "Cito",
    "Статус",
    "Комментарий",
    "Период",
)

_DATETIME_FORMATS = (
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
)
_SERVICE_BY_INPUT = {
    str(value).strip().casefold(): code
    for code, label in SERVICE_CHOICES
    for value in (code, label)
}
_STATUS_BY_INPUT = {
    str(value).strip().casefold(): code
    for code, label in WaitingListStatus.choices
    for value in (code, label)
}
_TRUE_VALUES = {"1", "да", "true", "yes"}
_FALSE_VALUES = {"0", "нет", "false", "no", ""}


class WaitingListImportError(ValueError):
    """Ошибка формата или значения в файле импорта."""


@dataclass(frozen=True)
class WaitingListImportRow:
    source_line: int
    patient_name: str
    patient_dob: date | None
    patient_phone: str
    service_id: str
    date_tag: date | None
    date_end: date | None
    priority_cito: bool
    comment: str
    status: str
    created_at: datetime | None
    history: tuple[tuple[datetime | None, str], ...]


def parse_waiting_list_file(path: Path) -> list[WaitingListImportRow]:
    """Прочитать и полностью проверить табличную UTF-8 выгрузку."""

    try:
        stream = path.open(encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise WaitingListImportError(f"Не удалось открыть файл {path}: {exc}") from exc

    with stream:
        return parse_waiting_list_stream(stream)


def parse_waiting_list_bytes(payload: bytes) -> list[WaitingListImportRow]:
    """Разобрать загруженный файл без промежуточной записи на диск."""

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WaitingListImportError(
            "Файл должен быть сохранён в кодировке UTF-8 или UTF-8 с BOM."
        ) from exc
    return parse_waiting_list_stream(StringIO(text, newline=""))


def parse_waiting_list_stream(stream) -> list[WaitingListImportRow]:
    """Разобрать уже открытый текстовый поток табличной выгрузки."""

    reader = csv.DictReader(stream, delimiter="\t")
    headers = tuple(reader.fieldnames or ())
    missing = [name for name in WAITING_LIST_EXPORT_HEADERS if name not in headers]
    if missing:
        raise WaitingListImportError(
            "В файле отсутствуют обязательные колонки: "
            + ", ".join(repr(name) for name in missing)
        )

    rows: list[WaitingListImportRow] = []
    errors: list[str] = []
    for source_line, raw_row in enumerate(reader, start=2):
        if None in raw_row:
            errors.append(f"строка {source_line}: лишние значения после последней колонки")
            continue
        if not any(_text(raw_row.get(name)) for name in WAITING_LIST_EXPORT_HEADERS):
            continue
        try:
            rows.append(_parse_row(raw_row, source_line=source_line))
        except WaitingListImportError as exc:
            errors.append(f"строка {source_line}: {exc}")

    if errors:
        shown = errors[:20]
        suffix = (
            f"\n... и ещё ошибок: {len(errors) - len(shown)}"
            if len(errors) > len(shown)
            else ""
        )
        raise WaitingListImportError("Ошибки в файле:\n" + "\n".join(shown) + suffix)
    if not rows:
        raise WaitingListImportError("Файл не содержит записей для импорта.")
    return rows


@transaction.atomic
def clear_waiting_list_data() -> tuple[int, int]:
    """Удалить первичные записи и каскадно связанный журнал."""

    entries = WaitingListEntry.objects.count()
    audit_rows = WaitingListAuditLog.objects.count()
    WaitingListEntry.objects.all().delete()
    return entries, audit_rows


@transaction.atomic
def import_waiting_list_rows(
    rows: list[WaitingListImportRow],
    *,
    author,
) -> tuple[int, int]:
    """Атомарно создать записи и журнал исходной истории изменений."""

    entries: list[WaitingListEntry] = []
    for row in rows:
        entry = WaitingListEntry(
            author=author,
            patient_name=row.patient_name,
            patient_dob=row.patient_dob,
            patient_phone=row.patient_phone,
            service_id=row.service_id,
            date_tag=row.date_tag,
            date_end=row.date_end,
            priority_cito=row.priority_cito,
            comment=row.comment,
            status=row.status,
        )
        try:
            entry.full_clean(validate_unique=False)
        except ValidationError as exc:
            raise WaitingListImportError(
                f"строка {row.source_line}: запись не прошла проверку модели: {exc}"
            ) from exc
        entries.append(entry)

    WaitingListEntry.objects.bulk_create(entries)

    timestamped_entries = []
    for row, entry in zip(rows, entries, strict=True):
        if row.created_at is None:
            continue
        entry.created_at = row.created_at
        entry.updated_at = row.created_at
        timestamped_entries.append(entry)
    if timestamped_entries:
        WaitingListEntry.objects.bulk_update(
            timestamped_entries,
            fields=("created_at", "updated_at"),
        )

    audit_rows: list[WaitingListAuditLog] = []
    audit_timestamps: list[tuple[WaitingListAuditLog, datetime]] = []
    for row, entry in zip(rows, entries, strict=True):
        history = row.history or (
            (row.created_at, "Запись импортирована из текстового файла"),
        )
        for event_time, action in history:
            audit = WaitingListAuditLog(
                entry=entry,
                actor=author,
                action=action,
            )
            audit_rows.append(audit)
            if event_time is not None:
                audit_timestamps.append((audit, event_time))

    WaitingListAuditLog.objects.bulk_create(audit_rows)
    timestamped_audits = []
    for audit, event_time in audit_timestamps:
        audit.created_at = event_time
        timestamped_audits.append(audit)
    if timestamped_audits:
        WaitingListAuditLog.objects.bulk_update(timestamped_audits, fields=("created_at",))

    return len(entries), len(audit_rows)


def _parse_row(raw_row: dict[str, str], *, source_line: int) -> WaitingListImportRow:
    patient_name = _text(raw_row.get("ФИО"))
    if len(patient_name) < 2:
        raise WaitingListImportError("ФИО обязательно (минимум 2 символа)")

    phone = _text(raw_row.get("Телефон"))
    phone_digits = re.sub(r"\D", "", phone)
    if len(phone_digits) != 11 or not phone_digits.startswith(("7", "8")):
        raise WaitingListImportError(f"некорректный телефон {phone!r}")

    service_raw = _text(raw_row.get("Услуга"))
    service_id = _SERVICE_BY_INPUT.get(service_raw.casefold())
    if service_id is None:
        allowed = ", ".join(label for _code, label in SERVICE_CHOICES)
        raise WaitingListImportError(
            f"неизвестная услуга {service_raw!r}; допустимо: {allowed}"
        )

    status_raw = _text(raw_row.get("Статус"))
    status = _STATUS_BY_INPUT.get(status_raw.casefold())
    if status is None:
        allowed = ", ".join(label for _code, label in WaitingListStatus.choices)
        raise WaitingListImportError(
            f"неизвестный статус {status_raw!r}; допустимо: {allowed}"
        )

    date_tag_value = _parse_optional_datetime(raw_row.get("Дата бирки"), "Дата бирки")
    date_end_value = _parse_optional_datetime(raw_row.get("Дата окончания"), "Дата окончания")
    date_tag = date_tag_value.date() if date_tag_value else None
    date_end = date_end_value.date() if date_end_value else None
    if date_tag and date_end and date_tag > date_end:
        raise WaitingListImportError("дата бирки позже даты окончания")

    comment = _text(raw_row.get("Комментарий"))
    appointment_date = _text(raw_row.get("Дата записи"))
    if appointment_date:
        _parse_optional_datetime(appointment_date, "Дата записи")
        imported_line = f"Дата записи (импорт): {appointment_date}"
        comment = f"{comment}\n{imported_line}".strip()

    history = _parse_history(_text(raw_row.get("История изменений")))
    return WaitingListImportRow(
        source_line=source_line,
        patient_name=patient_name,
        patient_dob=_parse_optional_date(raw_row.get("Дата рождения"), "Дата рождения"),
        patient_phone=phone,
        service_id=service_id,
        date_tag=date_tag,
        date_end=date_end,
        priority_cito=_parse_bool(raw_row.get("Cito")),
        comment=comment,
        status=status,
        created_at=_parse_optional_datetime(raw_row.get("Период"), "Период"),
        history=history,
    )


def _parse_history(value: str) -> tuple[tuple[datetime | None, str], ...]:
    history = []
    for raw_line in value.splitlines():
        action = raw_line.strip()
        if not action:
            continue
        if len(action) > WaitingListAuditLog._meta.get_field("action").max_length:
            raise WaitingListImportError("строка истории длиннее 255 символов")
        event_time = None
        date_prefix = action.split(" - ", 1)[0]
        try:
            event_time = _aware(datetime.strptime(date_prefix, "%d.%m.%y"))
        except ValueError:
            pass
        history.append((event_time, action))
    return tuple(history)


def _parse_optional_date(value: object, field_name: str) -> date | None:
    parsed = _parse_optional_datetime(value, field_name)
    return parsed.date() if parsed else None


def _parse_optional_datetime(value: object, field_name: str) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    for date_format in _DATETIME_FORMATS:
        try:
            return _aware(datetime.strptime(text, date_format))
        except ValueError:
            continue
    raise WaitingListImportError(
        f"поле {field_name!r}: неизвестный формат даты {text!r}"
    )


def _parse_bool(value: object) -> bool:
    text = _text(value).casefold()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise WaitingListImportError(f"поле 'Cito': неизвестное значение {_text(value)!r}")


def _aware(value: datetime) -> datetime:
    return timezone.make_aware(value, timezone.get_current_timezone())


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()
