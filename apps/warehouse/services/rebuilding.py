from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.warehouse.models import StockBalance, StockEntry, WarehouseAuditEvent
from apps.warehouse.policies import require_warehouse_scope
from apps.core.models import Department


@dataclass(frozen=True, order=True)
class _BalanceKey:
    department_id: int
    warehouse_id: int
    location_id: int
    lot_id: int
    funding_source_id: int


def _authorized_entries(*, actor, department_id):
    if department_id is None:
        if not actor.is_active or not actor.is_superuser:
            raise PermissionDenied(
                "Полную проверку остатков может выполнять только superuser."
            )
        return StockEntry.objects.all(), StockBalance.objects.all()
    department = Department.objects.get(pk=department_id)
    require_warehouse_scope(
        actor=actor, capability="warehouse_adjust_scope", department=department
    )
    return (
        StockEntry.objects.filter(department_id=department_id),
        StockBalance.objects.filter(department_id=department_id),
    )


def stock_balance_mismatches(*, actor, department_id: int | None = None) -> list[dict]:
    entries, balances = _authorized_entries(actor=actor, department_id=department_id)
    expected: dict[_BalanceKey, Decimal] = defaultdict(Decimal)
    for entry in entries.iterator():
        expected[
            _BalanceKey(
                entry.department_id,
                entry.warehouse_id,
                entry.location_id,
                entry.lot_id,
                entry.funding_source_id,
            )
        ] += entry.quantity
    actual = {
        _BalanceKey(
            balance.department_id,
            balance.warehouse_id,
            balance.location_id,
            balance.lot_id,
            balance.funding_source_id,
        ): balance.quantity
        for balance in balances.iterator()
    }
    mismatches = []
    for key in sorted(set(expected) | set(actual)):
        expected_quantity = expected.get(key, Decimal(0))
        actual_quantity = actual.get(key, Decimal(0))
        if expected_quantity != actual_quantity:
            mismatches.append(
                {
                    "department_id": key.department_id,
                    "warehouse_id": key.warehouse_id,
                    "location_id": key.location_id,
                    "lot_id": key.lot_id,
                    "funding_source_id": key.funding_source_id,
                    "expected": str(expected_quantity),
                    "actual": str(actual_quantity),
                }
            )
    return mismatches


@transaction.atomic
def rebuild_stock_balances(*, actor, department_id: int | None = None) -> int:
    if department_id is None:
        if not actor.is_active or not actor.is_superuser:
            raise PermissionDenied("Полную пересборку остатков может выполнять только superuser.")
        entries = StockEntry.objects.all()
        StockBalance.objects.all().delete()
    else:
        department = Department.objects.select_for_update().get(pk=department_id)
        require_warehouse_scope(
            actor=actor, capability="warehouse_adjust_scope", department=department
        )
        entries = StockEntry.objects.filter(department_id=department_id)
        StockBalance.objects.filter(department_id=department_id).delete()

    totals: dict[_BalanceKey, Decimal] = defaultdict(Decimal)
    for entry in entries.iterator():
        key = _BalanceKey(
            entry.department_id,
            entry.warehouse_id,
            entry.location_id,
            entry.lot_id,
            entry.funding_source_id,
        )
        totals[key] += entry.quantity
    negative = [key for key, quantity in totals.items() if quantity < 0]
    if negative:
        raise ValueError("Журнал содержит отрицательный итог; пересборка отменена.")
    balances = StockBalance.objects.bulk_create(
        [
            StockBalance(
                department_id=key.department_id,
                warehouse_id=key.warehouse_id,
                location_id=key.location_id,
                lot_id=key.lot_id,
                funding_source_id=key.funding_source_id,
                quantity=quantity,
            )
            for key, quantity in sorted(totals.items())
            if quantity
        ]
    )
    WarehouseAuditEvent.objects.create(
        actor=actor,
        department_id=department_id,
        action="balances.rebuilt",
        object_type="StockBalance",
        object_id=str(department_id or "all"),
        reason="Проверочная пересборка проекции из журнала проводок",
        summary={"department_id": department_id, "balance_count": len(balances)},
    )
    return len(balances)
