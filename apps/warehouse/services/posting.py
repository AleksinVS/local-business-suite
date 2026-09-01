from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import uuid

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
)
from apps.warehouse.policies import require_warehouse_scope


class WarehousePostingError(ValidationError):
    """Ошибка бизнес-инварианта, при которой документ не проводится."""


@dataclass(frozen=True, order=True)
class _BalanceKey:
    department_id: int
    warehouse_id: int
    location_id: int
    lot_id: int
    funding_source_id: int


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
        lot_id=line.lot_id,
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


def _validate_location(location: StorageLocation, *, incoming: bool) -> None:
    if location is None:
        raise WarehousePostingError("В строке не указан обязательный адрес хранения.")
    if incoming and not location.is_active:
        raise WarehousePostingError(
            {"destination_location": "Нельзя размещать остаток в неактивном адресе."}
        )


def _validate_fefo(document: StockDocument, line: StockDocumentLine) -> None:
    if document.document_type != StockDocument.DocumentType.ISSUE:
        return
    if line.source_location.purpose != StorageLocation.Purpose.AVAILABLE:
        raise WarehousePostingError(
            {"source_location": "Выдача разрешена только из доступного адреса."}
        )
    if line.lot.expires_on and line.lot.expires_on < document.operation_date:
        raise WarehousePostingError({"lot": "Нельзя выдать просроченную партию."})

    earliest = (
        StockBalance.objects.filter(
            department_id=document.department_id,
            lot__item_id=line.item_id,
            funding_source_id=line.funding_source_id,
            location__purpose=StorageLocation.Purpose.AVAILABLE,
            location__is_active=True,
            quantity__gt=0,
        )
        .exclude(lot__expires_on__lt=document.operation_date)
        .exclude(lot__expires_on__isnull=True)
        .select_related("lot")
        .order_by("lot__expires_on", "lot__batch_number", "lot_id")
        .first()
    )
    selected_expiry = line.lot.expires_on
    if earliest and (selected_expiry is None or earliest.lot.expires_on < selected_expiry):
        if not line.fefo_override_reason.strip():
            raise WarehousePostingError(
                {
                    "fefo_override_reason": (
                        "Выбрана не ближайшая по сроку годности доступная партия; "
                        "укажите причину отклонения от FEFO."
                    )
                }
            )


def _load_lines(document: StockDocument) -> list[StockDocumentLine]:
    lines = list(
        document.lines.select_related(
            "item__unit",
            "lot",
            "funding_source",
            "source_location__warehouse",
            "destination_location__warehouse",
        ).order_by("sequence", "id")
    )
    if not lines:
        raise WarehousePostingError("Нельзя провести документ без строк.")
    for line in lines:
        line.full_clean()
    return lines


def _apply_movements(
    *, document: StockDocument, lines: list[StockDocumentLine]
) -> list[StockEntry]:
    deltas: dict[_BalanceKey, Decimal] = defaultdict(Decimal)
    entry_specs: list[tuple[StockDocumentLine, StorageLocation, Decimal]] = []
    locations: dict[int, StorageLocation] = {}

    for line in lines:
        _validate_fefo(document, line)
        for location, quantity in _movement_specs(document, line):
            _validate_location(location, incoming=quantity > 0)
            locations[location.pk] = location
            key = _key_for(line, location)
            deltas[key] += quantity
            entry_specs.append((line, location, quantity))

    list(
        StorageLocation.objects.select_for_update()
        .filter(pk__in=sorted(locations))
        .order_by("pk")
    )
    keys = sorted(deltas)
    existing = {
        _BalanceKey(
            balance.department_id,
            balance.warehouse_id,
            balance.location_id,
            balance.lot_id,
            balance.funding_source_id,
        ): balance
        for balance in StockBalance.objects.select_for_update()
        .filter(
            department_id=document.department_id,
            location_id__in=[key.location_id for key in keys],
            lot_id__in=[key.lot_id for key in keys],
            funding_source_id__in=[key.funding_source_id for key in keys],
        )
        .order_by("department_id", "warehouse_id", "location_id", "lot_id", "funding_source_id")
    }

    balances: dict[_BalanceKey, StockBalance] = {}
    for key in keys:
        balance = existing.get(key)
        if balance is None:
            try:
                with transaction.atomic():
                    balance = StockBalance.objects.create(
                        department_id=key.department_id,
                        warehouse_id=key.warehouse_id,
                        location_id=key.location_id,
                        lot_id=key.lot_id,
                        funding_source_id=key.funding_source_id,
                        quantity=0,
                    )
            except IntegrityError:
                balance = StockBalance.objects.select_for_update().get(
                    department_id=key.department_id,
                    warehouse_id=key.warehouse_id,
                    location_id=key.location_id,
                    lot_id=key.lot_id,
                    funding_source_id=key.funding_source_id,
                )
        resulting_quantity = balance.quantity + deltas[key]
        if resulting_quantity < 0:
            raise WarehousePostingError(
                "Операция создаёт отрицательный остаток. Проведение отменено."
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
            lot_id=line.lot_id,
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
        for line in source.lines.select_related("item", "lot", "funding_source").all()
    }
    if set(line_by_sequence) != set(source_lines):
        raise WarehousePostingError("Строки сторно не соответствуют исходному документу.")
    for sequence, reversal_line in line_by_sequence.items():
        original_line = source_lines[sequence]
        if (
            reversal_line.item_id != original_line.item_id
            or reversal_line.lot_id != original_line.lot_id
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
            entry.lot_id,
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
            balance.lot_id,
            balance.funding_source_id,
        ): balance
        for balance in StockBalance.objects.select_for_update()
        .filter(
            department_id=document.department_id,
            location_id__in=location_ids,
        )
        .order_by("department_id", "warehouse_id", "location_id", "lot_id", "funding_source_id")
    }
    for key, delta in sorted(deltas.items()):
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
                lot_id=entry.lot_id,
                unit_id=entry.unit_id,
                funding_source_id=entry.funding_source_id,
                quantity=quantity,
                operation_date=document.operation_date,
            )
            for line, entry, quantity in reversed_specs
        ]
    )


@transaction.atomic
def post_document(*, document_id: int, actor) -> StockDocument:
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
    document.full_clean()
    lines = _load_lines(document)
    if document.document_type == StockDocument.DocumentType.REVERSAL:
        entries = _apply_reversal(document=document, lines=lines)
    else:
        entries = _apply_movements(document=document, lines=lines)
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
                lot=line.lot,
                funding_source=line.funding_source,
                quantity=line.quantity,
                source_location=line.source_location,
                destination_location=line.destination_location,
            )
            for line in source.lines.select_related(
                "item", "lot", "funding_source", "source_location", "destination_location"
            ).order_by("sequence", "id")
        ]
    )
    return post_document(document_id=reversal.pk, actor=actor)
