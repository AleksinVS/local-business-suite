from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.warehouse.models import (
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StockEntry,
    StorageLocation,
    WarehouseAuditEvent,
    WarehouseItem,
)
from apps.warehouse.policies import require_warehouse_scope


class WarehousePostingError(ValidationError):
    """Ошибка бизнес-инварианта, при которой документ не проводится."""

    def __init__(self, message, *, line_sequence=None, line_index=None, field=None):
        super().__init__(message)
        self.line_sequence = line_sequence
        self.line_index = line_index
        self.field = field


def _line_error(line, field, message):
    return WarehousePostingError(
        {field: message}, line_sequence=line.sequence, field=field
    )


def _annotate_line_error(error, line, *, line_index=None, field=None):
    """Attach stable row identity without parsing human-facing text."""
    if getattr(error, "line_sequence", None) is None:
        error.line_sequence = line.sequence
    if getattr(error, "line_index", None) is None:
        error.line_index = line_index
    if getattr(error, "field", None) is None and field:
        error.field = field
    return error


@dataclass(frozen=True)
class _BalanceKey:
    department_id: int
    warehouse_id: int
    location_id: int
    item_id: int
    series_key: str
    expires_on: date | None
    funding_source_id: int


def _key_sort_value(key: _BalanceKey):
    return (
        key.department_id,
        key.warehouse_id,
        key.location_id,
        key.item_id,
        key.series_key,
        key.expires_on is None,
        key.expires_on or date.max,
        key.funding_source_id,
    )


def _normalized_quantity(line: StockDocumentLine) -> Decimal:
    try:
        quantity = Decimal(line.quantity)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WarehousePostingError({"quantity": "Некорректное количество."}) from exc
    if quantity <= 0:
        raise WarehousePostingError({"quantity": "Количество должно быть больше нуля."})
    precision = line.item.unit.quantity_precision
    quantum = Decimal(1).scaleb(-precision)
    if quantity != quantity.quantize(quantum):
        raise WarehousePostingError(
            {
                "quantity": (
                    f"Единица «{line.item.unit}» допускает не более "
                    f"{precision} знаков после запятой."
                )
            }
        )
    return quantity


def _key_for(line: StockDocumentLine, location: StorageLocation) -> _BalanceKey:
    return _BalanceKey(
        department_id=line.document.department_id,
        warehouse_id=location.warehouse_id,
        location_id=location.pk,
        item_id=line.item_id,
        series_key=line.series_key,
        expires_on=line.expires_on,
        funding_source_id=line.funding_source_id,
    )


def _movement_specs(
    document: StockDocument, line: StockDocumentLine
) -> tuple[tuple[StorageLocation, Decimal], ...]:
    quantity = _normalized_quantity(line)
    document_type = document.document_type
    if document_type in {
        StockDocument.DocumentType.OPENING,
        StockDocument.DocumentType.RECEIPT,
    }:
        return ((line.destination_location, quantity),)
    if document_type in {
        StockDocument.DocumentType.ISSUE,
        StockDocument.DocumentType.WRITEOFF,
    }:
        return ((line.source_location, -quantity),)
    if document_type == StockDocument.DocumentType.RELOCATION:
        return (
            (line.source_location, -quantity),
            (line.destination_location, quantity),
        )
    if document_type == StockDocument.DocumentType.ADJUSTMENT:
        if line.source_location_id:
            return ((line.source_location, -quantity),)
        return ((line.destination_location, quantity),)
    raise WarehousePostingError("Неподдерживаемый тип складского документа.")


def _validate_location(
    location: StorageLocation,
    *,
    incoming: bool,
    document_type: str,
    allow_legacy_unassigned: bool = False,
) -> None:
    if location is None:
        raise WarehousePostingError("В строке не указан обязательный адрес хранения.")
    ordinary_document = document_type in {
        StockDocument.DocumentType.OPENING,
        StockDocument.DocumentType.RECEIPT,
        StockDocument.DocumentType.ISSUE,
        StockDocument.DocumentType.WRITEOFF,
    }
    if ordinary_document and not location.is_active:
        raise WarehousePostingError(
            {
                "destination_location" if incoming else "source_location":
                "Обычная операция разрешена только в активном адресе."
            }
        )
    legacy_unassigned_opening = (
        allow_legacy_unassigned
        and document_type == StockDocument.DocumentType.OPENING
        and location.purpose == StorageLocation.Purpose.UNASSIGNED
    )
    if (
        ordinary_document
        and location.purpose != StorageLocation.Purpose.AVAILABLE
        and not legacy_unassigned_opening
    ):
        field = "destination_location" if incoming else "source_location"
        raise WarehousePostingError(
            {field: "Обычная операция разрешена только в доступном адресе."}
        )


def _validate_fefo(document: StockDocument, line: StockDocumentLine) -> None:
    if document.document_type != StockDocument.DocumentType.ISSUE:
        return
    if line.source_location.purpose != StorageLocation.Purpose.AVAILABLE:
        raise _line_error(line, "source_location", "Выдача разрешена только из доступного адреса.")
    if line.expires_on and line.expires_on < document.operation_date:
        raise _line_error(line, "expires_on", "Нельзя выдать просроченную серию.")

    earliest = (
        StockBalance.objects.filter(
            department_id=document.department_id,
            item_id=line.item_id,
            funding_source_id=line.funding_source_id,
            location__purpose=StorageLocation.Purpose.AVAILABLE,
            location__is_active=True,
            quantity__gt=0,
        )
        .exclude(expires_on__lt=document.operation_date)
        .exclude(expires_on__isnull=True)
        .order_by("expires_on", "series_key", "id")
        .first()
    )
    selected_expiry = line.expires_on
    if earliest and (selected_expiry is None or earliest.expires_on < selected_expiry):
        if not line.fefo_override_reason.strip():
            raise _line_error(
                line,
                "fefo_override_reason",
                "Выбрана не ближайшая по сроку годности доступная серия; "
                "укажите причину отклонения от FEFO.",
            )


def _load_lines(document: StockDocument) -> list[StockDocumentLine]:
    lines = list(
        document.lines.select_related(
            "item__unit",
            "funding_source",
            "source_location__warehouse",
            "destination_location__warehouse",
        ).order_by("sequence", "id")
    )
    if not lines:
        raise WarehousePostingError("Нельзя провести документ без строк.")
    expiries_by_series: dict[tuple[int, str], set[date | None]] = defaultdict(set)
    for line_index, line in enumerate(lines):
        try:
            line.full_clean()
        except ValidationError as exc:
            raise _annotate_line_error(
                WarehousePostingError(exc), line, line_index=line_index
            ) from exc
        if line.series_key:
            expiries_by_series[(line.item_id, line.series_key)].add(line.expires_on)
    if any(len(expiries) > 1 for expiries in expiries_by_series.values()):
        raise WarehousePostingError(
            {"expires_on": "Одна серия позиции указана с разными сроками годности."}
        )
    return lines


def _lock_document_items(document: StockDocument) -> tuple[int, ...]:
    """Serialize series validation/posting for every item in the document.

    The item row is the stable database barrier available without restoring a
    separate series table.  A transaction waiting here observes the entries
    committed by the preceding transaction before ``_load_lines`` performs the
    series/expiry conflict check again.
    """

    item_ids = tuple(
        sorted(set(document.lines.values_list("item_id", flat=True)))
    )
    return tuple(
        WarehouseItem.objects.select_for_update()
        .filter(pk__in=item_ids)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _apply_movements(
    *,
    document: StockDocument,
    lines: list[StockDocumentLine],
    allow_legacy_unassigned: bool = False,
) -> list[StockEntry]:
    deltas: dict[_BalanceKey, Decimal] = defaultdict(Decimal)
    entry_specs: list[tuple[StockDocumentLine, StorageLocation, Decimal]] = []
    locations: dict[int, StorageLocation] = {}
    samples: dict[_BalanceKey, StockDocumentLine] = {}

    for line_index, line in enumerate(lines):
        try:
            _validate_fefo(document, line)
            movement_specs = _movement_specs(document, line)
        except WarehousePostingError as exc:
            raise _annotate_line_error(exc, line, line_index=line_index) from exc
        for location, quantity in movement_specs:
            try:
                _validate_location(
                    location,
                    incoming=quantity > 0,
                    document_type=document.document_type,
                    allow_legacy_unassigned=allow_legacy_unassigned,
                )
            except WarehousePostingError as exc:
                field = "destination_location" if quantity > 0 else "source_location"
                raise _annotate_line_error(
                    exc, line, line_index=line_index, field=field
                ) from exc
            locations[location.pk] = location
            key = _key_for(line, location)
            deltas[key] += quantity
            samples.setdefault(key, line)
            entry_specs.append((line, location, quantity))

    list(
        StorageLocation.objects.select_for_update()
        .filter(pk__in=sorted(locations))
        .order_by("pk")
    )
    keys = sorted(deltas, key=_key_sort_value)
    existing = {
        _BalanceKey(
            balance.department_id,
            balance.warehouse_id,
            balance.location_id,
            balance.item_id,
            balance.series_key,
            balance.expires_on,
            balance.funding_source_id,
        ): balance
        for balance in StockBalance.objects.select_for_update()
        .filter(
            department_id=document.department_id,
            location_id__in=[key.location_id for key in keys],
            item_id__in=[key.item_id for key in keys],
            funding_source_id__in=[key.funding_source_id for key in keys],
        )
        .order_by(
            "department_id",
            "warehouse_id",
            "location_id",
            "item_id",
            "series_key",
            "expires_on",
            "funding_source_id",
        )
    }

    balances: dict[_BalanceKey, StockBalance] = {}
    for key in keys:
        balance = existing.get(key)
        if balance is None:
            sample = samples[key]
            try:
                with transaction.atomic():
                    balance = StockBalance.objects.create(
                        department_id=key.department_id,
                        warehouse_id=key.warehouse_id,
                        location_id=key.location_id,
                        item_id=key.item_id,
                        series=sample.series,
                        series_key=key.series_key,
                        expires_on=key.expires_on,
                        incomplete_reason=sample.incomplete_reason,
                        funding_source_id=key.funding_source_id,
                        quantity=0,
                    )
            except IntegrityError:
                balance = StockBalance.objects.select_for_update().get(
                    department_id=key.department_id,
                    warehouse_id=key.warehouse_id,
                    location_id=key.location_id,
                    item_id=key.item_id,
                    series_key=key.series_key,
                    expires_on=key.expires_on,
                    funding_source_id=key.funding_source_id,
                )
        resulting_quantity = balance.quantity + deltas[key]
        if resulting_quantity < 0:
            sample = samples[key]
            raise _line_error(
                sample,
                "quantity",
                "Операция создаёт отрицательный остаток. Проведение отменено.",
            )
        balance.quantity = resulting_quantity
        balance.updated_at = timezone.now()
        balances[key] = balance

    StockBalance.objects.bulk_update(balances.values(), ["quantity", "updated_at"])
    entries = [
        StockEntry(
            document=document,
            document_line=line,
            department_id=document.department_id,
            warehouse_id=location.warehouse_id,
            location_id=location.pk,
            item_id=line.item_id,
            series=line.series,
            series_key=line.series_key,
            expires_on=line.expires_on,
            incomplete_reason=line.incomplete_reason,
            unit_id=line.item.unit_id,
            funding_source_id=line.funding_source_id,
            quantity=quantity,
            operation_date=document.operation_date,
        )
        for line, location, quantity in entry_specs
    ]
    return StockEntry.objects.bulk_create(entries)


def _apply_reversal(
    *, document: StockDocument, lines: list[StockDocumentLine]
) -> list[StockEntry]:
    source = StockDocument.objects.select_for_update().get(pk=document.reverses_document_id)
    if source.status != StockDocument.Status.POSTED:
        raise WarehousePostingError("Сторнировать можно только проведённый документ.")
    if source.document_type == StockDocument.DocumentType.REVERSAL or source.is_reversed:
        raise WarehousePostingError("Документ уже сторнирован или сам является сторно.")
    line_by_sequence = {line.sequence: line for line in lines}
    source_lines = {
        line.sequence: line
        for line in source.lines.select_related("item", "funding_source").all()
    }
    if set(line_by_sequence) != set(source_lines):
        raise WarehousePostingError("Строки сторно не соответствуют исходному документу.")
    for sequence, reversal_line in line_by_sequence.items():
        original_line = source_lines[sequence]
        if (
            reversal_line.item_id != original_line.item_id
            or reversal_line.series != original_line.series
            or reversal_line.series_key != original_line.series_key
            or reversal_line.expires_on != original_line.expires_on
            or reversal_line.incomplete_reason != original_line.incomplete_reason
            or reversal_line.funding_source_id != original_line.funding_source_id
            or reversal_line.quantity != original_line.quantity
            or reversal_line.source_location_id != original_line.source_location_id
            or reversal_line.destination_location_id
            != original_line.destination_location_id
        ):
            raise WarehousePostingError(
                "Содержимое строк сторно должно точно совпадать с исходным документом."
            )
    original_entries = list(
        source.entries.select_related("document_line", "location").order_by("id")
    )
    if not original_entries:
        raise WarehousePostingError("У исходного документа нет проводок.")

    deltas: dict[_BalanceKey, Decimal] = defaultdict(Decimal)
    reversed_specs = []
    location_ids = set()
    for entry in original_entries:
        reversal_line = line_by_sequence.get(entry.document_line.sequence)
        if reversal_line is None:
            raise WarehousePostingError("Строки сторно не соответствуют исходному документу.")
        key = _BalanceKey(
            entry.department_id,
            entry.warehouse_id,
            entry.location_id,
            entry.item_id,
            entry.series_key,
            entry.expires_on,
            entry.funding_source_id,
        )
        quantity = -entry.quantity
        deltas[key] += quantity
        reversed_specs.append((reversal_line, entry, quantity))
        location_ids.add(entry.location_id)

    list(
        StorageLocation.objects.select_for_update()
        .filter(pk__in=sorted(location_ids))
        .order_by("pk")
    )
    balances = {
        _BalanceKey(
            balance.department_id,
            balance.warehouse_id,
            balance.location_id,
            balance.item_id,
            balance.series_key,
            balance.expires_on,
            balance.funding_source_id,
        ): balance
        for balance in StockBalance.objects.select_for_update()
        .filter(
            department_id=document.department_id,
            location_id__in=location_ids,
        )
        .order_by(
            "department_id",
            "warehouse_id",
            "location_id",
            "item_id",
            "series_key",
            "expires_on",
            "funding_source_id",
        )
    }
    for key, delta in sorted(deltas.items(), key=lambda item: _key_sort_value(item[0])):
        balance = balances.get(key)
        if balance is None or balance.quantity + delta < 0:
            raise WarehousePostingError(
                "Сторно невозможно: последующие операции уже изменили доступный остаток."
            )
        balance.quantity += delta
        balance.updated_at = timezone.now()
    StockBalance.objects.bulk_update(balances.values(), ["quantity", "updated_at"])
    return StockEntry.objects.bulk_create(
        [
            StockEntry(
                document=document,
                document_line=line,
                department_id=entry.department_id,
                warehouse_id=entry.warehouse_id,
                location_id=entry.location_id,
                item_id=entry.item_id,
                series=entry.series,
                series_key=entry.series_key,
                expires_on=entry.expires_on,
                incomplete_reason=entry.incomplete_reason,
                unit_id=entry.unit_id,
                funding_source_id=entry.funding_source_id,
                quantity=quantity,
                operation_date=document.operation_date,
            )
            for line, entry, quantity in reversed_specs
        ]
    )


@transaction.atomic
def post_document(
    *, document_id: int, actor, allow_legacy_unassigned: bool = False
) -> StockDocument:
    document = (
        StockDocument.objects.select_for_update()
        .select_related("department")
        .get(pk=document_id)
    )
    capability = (
        "warehouse_adjust_scope"
        if document.document_type
        in {
            StockDocument.DocumentType.WRITEOFF,
            StockDocument.DocumentType.ADJUSTMENT,
            StockDocument.DocumentType.REVERSAL,
        }
        else "warehouse_operate_scope"
    )
    require_warehouse_scope(
        actor=actor, capability=capability, department=document.department
    )
    if document.status == StockDocument.Status.POSTED:
        return document
    if document.status != StockDocument.Status.DRAFT:
        raise WarehousePostingError("Провести можно только черновик.")
    allow_legacy_unassigned = bool(
        allow_legacy_unassigned
        and document.document_type == StockDocument.DocumentType.OPENING
        and str(document.external_source_id or "").startswith("legacy:")
        and get_user_model().objects.filter(
            pk=getattr(actor, "pk", None), is_active=True, is_superuser=True
        ).exists()
    )
    document.full_clean()
    _lock_document_items(document)
    # Re-read and validate after the item locks. This closes the race where two
    # receipts introduce the same normalized series with different expiries.
    lines = _load_lines(document)
    if document.document_type == StockDocument.DocumentType.REVERSAL:
        entries = _apply_reversal(document=document, lines=lines)
    else:
        entries = _apply_movements(
            document=document,
            lines=lines,
            allow_legacy_unassigned=allow_legacy_unassigned,
        )
    document.status = StockDocument.Status.POSTED
    document.posted_by = actor
    document.posted_at = timezone.now()
    document.save(update_fields=["status", "posted_by", "posted_at", "updated_at"])
    WarehouseAuditEvent.objects.create(
        actor=actor,
        department=document.department,
        action="document.posted",
        object_type="StockDocument",
        object_id=str(document.pk),
        correlation_id=document.idempotency_key or uuid.uuid4(),
        summary={
            "document_type": document.document_type,
            "department_id": document.department_id,
            "entry_count": len(entries),
        },
    )
    return document


@transaction.atomic
def cancel_draft_document(*, document_id: int, actor, reason: str) -> StockDocument:
    document = StockDocument.objects.select_for_update().select_related("department").get(
        pk=document_id
    )
    require_warehouse_scope(
        actor=actor, capability="warehouse_operate_scope", department=document.department
    )
    if document.status != StockDocument.Status.DRAFT:
        raise WarehousePostingError("Отменить можно только черновик.")
    if not reason.strip():
        raise WarehousePostingError({"reason": "Укажите причину отмены."})
    document.status = StockDocument.Status.CANCELLED
    document.reason = reason.strip()
    document.save(update_fields=["status", "reason", "updated_at"])
    WarehouseAuditEvent.objects.create(
        actor=actor,
        department=document.department,
        action="document.cancelled",
        object_type="StockDocument",
        object_id=str(document.pk),
        reason=reason.strip(),
        summary={"department_id": document.department_id},
    )
    return document


@transaction.atomic
def reverse_document(
    *, source_document_id: int, actor, operation_date: date, reason: str
) -> StockDocument:
    source = (
        StockDocument.objects.select_for_update()
        .select_related("department")
        .get(pk=source_document_id)
    )
    require_warehouse_scope(
        actor=actor,
        capability="warehouse_adjust_scope",
        department=source.department,
    )
    if source.status != StockDocument.Status.POSTED:
        raise WarehousePostingError("Сторнировать можно только проведённый документ.")
    if source.document_type == StockDocument.DocumentType.REVERSAL or source.is_reversed:
        raise WarehousePostingError("Документ уже сторнирован или сам является сторно.")
    if not reason.strip():
        raise WarehousePostingError({"reason": "Для сторно нужна причина."})
    if operation_date < source.operation_date:
        raise WarehousePostingError(
            {"operation_date": "Дата сторно не может быть раньше исходной операции."}
        )
    reversal = StockDocument.objects.create(
        department=source.department,
        document_type=StockDocument.DocumentType.REVERSAL,
        operation_date=operation_date,
        reason=reason.strip(),
        created_by=actor,
        reverses_document=source,
        idempotency_key=uuid.uuid4(),
    )
    reversal.lines.bulk_create(
        [
            StockDocumentLine(
                document=reversal,
                sequence=line.sequence,
                item=line.item,
                series=line.series,
                series_key=line.series_key,
                expires_on=line.expires_on,
                incomplete_reason=line.incomplete_reason,
                funding_source=line.funding_source,
                quantity=line.quantity,
                source_location=line.source_location,
                destination_location=line.destination_location,
            )
            for line in source.lines.select_related(
                "item", "funding_source", "source_location", "destination_location"
            ).order_by("sequence", "id")
        ]
    )
    return post_document(document_id=reversal.pk, actor=actor)
