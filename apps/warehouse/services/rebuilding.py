from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.core.models import Department
from apps.warehouse.models import StockBalance, StockEntry, WarehouseAuditEvent
from apps.warehouse.policies import require_warehouse_scope


@dataclass(frozen=True)
class _BalanceKey:
    department_id: int
    warehouse_id: int
    location_id: int
    item_id: int
    series_key: str
    expires_on: date | None
    funding_source_id: int


def _projection_sort_key(key: _BalanceKey):
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


def _key_from_row(row) -> _BalanceKey:
    return _BalanceKey(
        row.department_id,
        row.warehouse_id,
        row.location_id,
        row.item_id,
        row.series_key,
        row.expires_on,
        row.funding_source_id,
    )


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


def _expected_totals(entries):
    totals: dict[_BalanceKey, Decimal] = defaultdict(Decimal)
    samples = {}
    for entry in entries.order_by("operation_date", "id").iterator():
        key = _key_from_row(entry)
        totals[key] += entry.quantity
        samples.setdefault(key, entry)
    return totals, samples


def _actual_totals(balances):
    totals: dict[_BalanceKey, Decimal] = defaultdict(Decimal)
    for balance in balances.iterator():
        totals[_key_from_row(balance)] += balance.quantity
    return totals


def _projection_checksum(totals: dict[_BalanceKey, Decimal]) -> str:
    payload = []
    for key in sorted(totals, key=_projection_sort_key):
        quantity = totals[key]
        if not quantity:
            continue
        payload.append(
            [
                key.department_id,
                key.warehouse_id,
                key.location_id,
                key.item_id,
                key.series_key,
                key.expires_on.isoformat() if key.expires_on else None,
                key.funding_source_id,
                format(quantity, "f"),
            ]
        )
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _journal_checksum(entries) -> tuple[int, str]:
    digest = sha256()
    count = 0
    fields = (
        "id",
        "document_id",
        "document_line_id",
        "department_id",
        "warehouse_id",
        "location_id",
        "item_id",
        "series",
        "series_key",
        "expires_on",
        "incomplete_reason",
        "unit_id",
        "funding_source_id",
        "quantity",
        "operation_date",
    )
    for row in entries.order_by("id").values_list(*fields).iterator():
        serializable = [
            value.isoformat()
            if hasattr(value, "isoformat")
            else format(value, "f")
            if isinstance(value, Decimal)
            else value
            for value in row
        ]
        digest.update(
            json.dumps(
                serializable, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        )
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


def _series_expiry_conflicts(entries) -> list[dict]:
    expiries: dict[tuple[int, str], set[date | None]] = defaultdict(set)
    for item_id, series_key, expires_on in entries.exclude(series_key="").values_list(
        "item_id", "series_key", "expires_on"
    ).iterator():
        expiries[(item_id, series_key)].add(expires_on)
    return [
        {
            "item_id": item_id,
            "series_key": series_key,
            "expires_on": sorted(
                (value.isoformat() if value else None for value in values),
                key=lambda value: (value is None, value or ""),
            ),
        }
        for (item_id, series_key), values in sorted(expiries.items())
        if len(values) > 1
    ]


def stock_balance_mismatches(*, actor, department_id: int | None = None) -> list[dict]:
    entries, balances = _authorized_entries(actor=actor, department_id=department_id)
    expected, _ = _expected_totals(entries)
    actual = _actual_totals(balances)
    mismatches = []
    for key in sorted(set(expected) | set(actual), key=_projection_sort_key):
        expected_quantity = expected.get(key, Decimal(0))
        actual_quantity = actual.get(key, Decimal(0))
        if expected_quantity != actual_quantity:
            mismatches.append(
                {
                    "department_id": key.department_id,
                    "warehouse_id": key.warehouse_id,
                    "location_id": key.location_id,
                    "item_id": key.item_id,
                    "series_key": key.series_key,
                    "expires_on": key.expires_on.isoformat() if key.expires_on else None,
                    "funding_source_id": key.funding_source_id,
                    "expected": str(expected_quantity),
                    "actual": str(actual_quantity),
                }
            )
    return mismatches


def inline_series_reconciliation(*, actor, department_id: int | None = None) -> dict:
    """Return checksums and integrity findings for the inline-series ledger."""

    entries, balances = _authorized_entries(actor=actor, department_id=department_id)
    expected, _ = _expected_totals(entries)
    actual = _actual_totals(balances)
    entry_count, journal_checksum = _journal_checksum(entries)
    conflicts = _series_expiry_conflicts(entries)
    mismatches = stock_balance_mismatches(actor=actor, department_id=department_id)
    expected_checksum = _projection_checksum(expected)
    actual_checksum = _projection_checksum(actual)
    return {
        "ok": not conflicts and not mismatches and expected_checksum == actual_checksum,
        "department_id": department_id,
        "entry_count": entry_count,
        "balance_count": balances.count(),
        "journal_checksum": journal_checksum,
        "expected_projection_checksum": expected_checksum,
        "actual_projection_checksum": actual_checksum,
        "series_expiry_conflicts": conflicts,
        "balance_mismatches": mismatches,
    }


@transaction.atomic
def record_inline_series_checkpoint(*, actor, department_id: int | None = None) -> dict:
    report = inline_series_reconciliation(actor=actor, department_id=department_id)
    if not report["ok"]:
        raise ValueError("Сверка inline-серий выявила конфликты или расхождения.")
    WarehouseAuditEvent.objects.create(
        actor=actor,
        department_id=department_id,
        action="inline_series.reconciled",
        object_type="WarehouseInlineSeriesMigration",
        object_id=str(department_id or "all"),
        reason="Контрольная сверка журнала и проекции inline-серий",
        summary={key: value for key, value in report.items() if key != "balance_mismatches"},
    )
    return report


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

    totals, samples = _expected_totals(entries)
    negative = [key for key, quantity in totals.items() if quantity < 0]
    if negative:
        raise ValueError("Журнал содержит отрицательный итог; пересборка отменена.")
    balances = StockBalance.objects.bulk_create(
        [
            StockBalance(
                department_id=key.department_id,
                warehouse_id=key.warehouse_id,
                location_id=key.location_id,
                item_id=key.item_id,
                series=samples[key].series,
                series_key=key.series_key,
                expires_on=key.expires_on,
                incomplete_reason=samples[key].incomplete_reason,
                funding_source_id=key.funding_source_id,
                quantity=quantity,
            )
            for key, quantity in sorted(
                totals.items(), key=lambda item: _projection_sort_key(item[0])
            )
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
