"""Atomic command for moving selected stock balances to one receiving address."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    QUANTITY_DECIMAL_PLACES,
    QUANTITY_MAX_DIGITS,
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StorageLocation,
    WarehouseItem,
)
from .relocation_selectors import (
    operable_stock_balances_queryset,
    relocatable_stock_balances_queryset,
    relocation_destination_locations_queryset,
    relocation_destination_warehouses_queryset,
)
from .services.posting import WarehousePostingError, post_document


class WarehouseRelocationError(WarehousePostingError):
    """The selected stock cannot be moved as one atomic operation."""


@dataclass(frozen=True)
class RelocationLineRequest:
    balance_id: int
    quantity: Decimal
    expected_quantity: Decimal


@transaction.atomic
def create_and_post_relocation(
    *,
    actor,
    lines: list[RelocationLineRequest] | tuple[RelocationLineRequest, ...],
    destination_warehouse_id: int,
    destination_location_id: int | None = None,
    operation_date: date | None = None,
    idempotency_key: uuid.UUID | str | None = None,
) -> StockDocument:
    """Create and post a single relocation after re-resolving every resource.

    The command locks items, locations and balance rows in the same stable order
    as regular posting.  The caller-provided snapshot is only a stale-write
    guard; access, current quantity and all destination invariants are resolved
    again inside this transaction.
    """

    requests = _normalize_requests(lines)
    request_ids = [line.balance_id for line in requests]
    command_key = _normalize_uuid(idempotency_key)
    command_date = operation_date or timezone.localdate()
    if not isinstance(command_date, date):
        raise WarehouseRelocationError("Некорректная дата перемещения.")

    preliminary = list(
        operable_stock_balances_queryset(actor)
        .filter(pk__in=request_ids)
        .select_related(
            "department", "warehouse", "location", "item__unit", "funding_source"
        )
    )
    if len(preliminary) != len(requests):
        raise PermissionDenied("Одна или несколько выбранных строк недоступны для перемещения.")
    department_ids = {balance.department_id for balance in preliminary}
    if len(department_ids) != 1:
        raise WarehouseRelocationError(
            "Одним документом можно перемещать остатки только одного подразделения."
        )
    department_id = next(iter(department_ids))

    destination_warehouse = (
        relocation_destination_warehouses_queryset(
            actor, department_id=department_id
        )
        .select_related("department", "default_receiving_location")
        .filter(pk=destination_warehouse_id)
        .first()
    )
    if destination_warehouse is None:
        raise PermissionDenied("Склад назначения недоступен для перемещения.")

    resolved_destination_id = destination_location_id
    if resolved_destination_id is None:
        resolved_destination_id = destination_warehouse.default_receiving_location_id
    if resolved_destination_id is None:
        raise WarehouseRelocationError(
            {
                "destination_location": (
                    "У склада не задан однозначный адрес приёмки; выберите адрес."
                )
            }
        )

    # Validate warehouse/location coherence before an idempotent replay can
    # return an existing document. Otherwise a reused key could hide a forged
    # warehouse paired with the original document's valid location.
    preliminary_destination = (
        relocation_destination_locations_queryset(
            actor,
            department_id=department_id,
            warehouse_id=destination_warehouse.pk,
        )
        .select_related("warehouse")
        .filter(pk=resolved_destination_id)
        .first()
    )
    if preliminary_destination is None:
        raise WarehouseRelocationError(
            {"destination_location": "Адрес не относится к складу назначения или недоступен."}
        )

    if command_key is not None:
        existing = _existing_idempotent_relocation(
            command_key,
            actor=actor,
            requests=requests,
            balances=preliminary,
            destination_warehouse_id=destination_warehouse.pk,
            destination_location_id=resolved_destination_id,
            operation_date=command_date,
        )
        if existing is not None:
            return existing

    # Every stock posting locks affected item rows before locations and balances.
    # Following that order prevents the quick command from creating a competing
    # lock graph with the regular document-posting path.
    item_ids = sorted({balance.item_id for balance in preliminary})
    list(
        WarehouseItem.objects.select_for_update()
        .filter(pk__in=item_ids)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    # A repeated browser submission waits on the same item barrier and then
    # resolves the document committed by the first request instead of failing
    # the now-stale balance snapshot.
    if command_key is not None:
        existing = _existing_idempotent_relocation(
            command_key,
            actor=actor,
            requests=requests,
            balances=preliminary,
            destination_warehouse_id=destination_warehouse.pk,
            destination_location_id=resolved_destination_id,
            operation_date=command_date,
        )
        if existing is not None:
            return existing

    location_ids = sorted(
        {balance.location_id for balance in preliminary} | {resolved_destination_id}
    )
    locked_locations = {
        location.pk: location
        for location in StorageLocation.objects.select_for_update(of=("self",))
        .select_related("warehouse")
        .filter(pk__in=location_ids)
        .order_by("pk")
    }
    destination_location = locked_locations.get(resolved_destination_id)
    if (
        destination_location is None
        or destination_location.warehouse_id != destination_warehouse.pk
        or destination_location.warehouse.department_id != department_id
        or not destination_location.warehouse.is_active
        or not destination_location.is_active
        or destination_location.purpose != StorageLocation.Purpose.AVAILABLE
    ):
        raise WarehouseRelocationError(
            {"destination_location": "Выбранный адрес назначения недоступен."}
        )

    locked_balances = list(
        relocatable_stock_balances_queryset(actor)
        .select_for_update(of=("self",))
        .select_related(
            "department", "warehouse", "location", "item__unit", "funding_source"
        )
        .filter(pk__in=request_ids)
        .order_by(
            "department_id",
            "warehouse_id",
            "location_id",
            "item_id",
            "series_key",
            "expires_on",
            "funding_source_id",
            "pk",
        )
    )
    if len(locked_balances) != len(requests):
        raise PermissionDenied("Одна или несколько выбранных строк больше недоступны.")

    request_by_id = {line.balance_id: line for line in requests}
    for balance in locked_balances:
        requested = request_by_id[balance.pk]
        if balance.department_id != department_id:
            raise WarehouseRelocationError(
                "Одним документом можно перемещать остатки только одного подразделения."
            )
        source_location = locked_locations.get(balance.location_id)
        if (
            source_location is None
            or not source_location.is_active
            or source_location.purpose != StorageLocation.Purpose.AVAILABLE
            or not source_location.warehouse.is_active
        ):
            raise WarehouseRelocationError("Исходный остаток недоступен для перемещения.")
        if source_location.pk == destination_location.pk:
            raise WarehouseRelocationError(
                {"destination_location": "Исходный и целевой адреса должны различаться."}
            )
        if balance.quantity != requested.expected_quantity:
            raise WarehouseRelocationError(
                {
                    "lines": (
                        f"Остаток строки {balance.pk} изменился. "
                        "Обновите список и повторите операцию."
                    )
                }
            )
        _validate_requested_quantity(balance, requested.quantity)

    document = StockDocument(
        department_id=department_id,
        document_type=StockDocument.DocumentType.RELOCATION,
        operation_date=command_date,
        created_by=actor,
        idempotency_key=command_key,
    )
    document.full_clean()
    document.save()

    for sequence, balance in enumerate(locked_balances, start=1):
        requested = request_by_id[balance.pk]
        line = StockDocumentLine(
            document=document,
            sequence=sequence,
            item=balance.item,
            series=balance.series,
            series_key=balance.series_key,
            expires_on=balance.expires_on,
            incomplete_reason=balance.incomplete_reason,
            funding_source=balance.funding_source,
            quantity=requested.quantity,
            source_location_id=balance.location_id,
            destination_location=destination_location,
        )
        line.full_clean()
        line.save()

    return post_document(document_id=document.pk, actor=actor)


def _normalize_requests(lines) -> tuple[RelocationLineRequest, ...]:
    normalized = []
    seen = set()
    for raw in lines or ():
        try:
            balance_id = int(raw.balance_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise WarehouseRelocationError("Некорректная строка остатка.") from exc
        if balance_id <= 0 or balance_id in seen:
            raise WarehouseRelocationError("Строки остатка не должны повторяться.")
        seen.add(balance_id)
        normalized.append(
            RelocationLineRequest(
                balance_id=balance_id,
                quantity=_decimal(raw.quantity, "Количество перемещения"),
                expected_quantity=_decimal(
                    raw.expected_quantity, "Ожидаемый остаток"
                ),
            )
        )
    if not normalized:
        raise WarehouseRelocationError("Выберите хотя бы одну строку остатка.")
    return tuple(normalized)


def _existing_idempotent_relocation(
    command_key: uuid.UUID,
    *,
    actor,
    requests,
    balances,
    destination_warehouse_id: int,
    destination_location_id: int,
    operation_date: date,
):
    existing = (
        StockDocument.objects.select_for_update()
        .filter(idempotency_key=command_key)
        .first()
    )
    if existing is None:
        return None
    if existing.document_type != StockDocument.DocumentType.RELOCATION:
        raise WarehouseRelocationError("Ключ операции уже использован.")
    if existing.status != StockDocument.Status.POSTED:
        raise WarehouseRelocationError("Предыдущая попытка перемещения не завершена.")
    if (
        existing.created_by_id != getattr(actor, "pk", None)
        or existing.operation_date != operation_date
        or existing.department_id not in {balance.department_id for balance in balances}
    ):
        raise WarehouseRelocationError(
            "Ключ операции использован для другого перемещения."
        )

    request_by_id = {request.balance_id: request for request in requests}
    expected_lines = Counter(
        (
            balance.location_id,
            balance.item_id,
            balance.series_key,
            balance.expires_on,
            balance.incomplete_reason,
            balance.funding_source_id,
            request_by_id[balance.pk].quantity,
            destination_warehouse_id,
            destination_location_id,
        )
        for balance in balances
    )
    actual_lines = Counter(
        (
            line.source_location_id,
            line.item_id,
            line.series_key,
            line.expires_on,
            line.incomplete_reason,
            line.funding_source_id,
            line.quantity,
            line.destination_location.warehouse_id,
            line.destination_location_id,
        )
        for line in existing.lines.select_related("destination_location").all()
    )
    if expected_lines != actual_lines:
        raise WarehouseRelocationError(
            "Ключ операции использован для другого перемещения."
        )
    return existing


def _decimal(value, label: str) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WarehouseRelocationError(f"{label}: некорректное значение.") from exc
    if not normalized.is_finite() or normalized <= 0:
        raise WarehouseRelocationError(f"{label} должно быть больше нуля.")
    exponent = normalized.as_tuple().exponent
    if not isinstance(exponent, int) or abs(exponent) > 64:
        raise WarehouseRelocationError(f"{label}: значение выходит за допустимые пределы.")
    digits = len(normalized.as_tuple().digits)
    if exponent >= 0:
        decimal_places = 0
        total_digits = digits + exponent
    else:
        decimal_places = -exponent
        total_digits = max(digits, decimal_places)
    if decimal_places > QUANTITY_DECIMAL_PLACES or total_digits > QUANTITY_MAX_DIGITS:
        raise WarehouseRelocationError(
            f"{label}: не более {QUANTITY_MAX_DIGITS} цифр, "
            f"из них {QUANTITY_DECIMAL_PLACES} после запятой."
        )
    return normalized


def _validate_requested_quantity(balance: StockBalance, quantity: Decimal) -> None:
    precision = balance.item.unit.quantity_precision
    quantum = Decimal(1).scaleb(-precision)
    try:
        has_invalid_precision = quantity != quantity.quantize(quantum)
    except InvalidOperation as exc:
        raise WarehouseRelocationError(
            {"lines": "Количество выходит за допустимые пределы."}
        ) from exc
    if has_invalid_precision:
        raise WarehouseRelocationError(
            {
                "lines": (
                    f"Единица «{balance.item.unit}» допускает не более "
                    f"{precision} знаков после запятой."
                )
            }
        )
    if quantity > balance.quantity:
        raise WarehouseRelocationError(
            {"lines": f"Для строки {balance.pk} указано больше доступного остатка."}
        )


def _normalize_uuid(value) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise WarehouseRelocationError("Некорректный ключ операции.") from exc
