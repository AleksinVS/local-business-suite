from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from ..models import StockDocument, StockEntry

ZERO = Decimal("0")


def _entries(department_ids, entries=None):
    """Return posted entries in the caller-provided department scope."""
    ids = tuple(department_ids) if department_ids is not None else None
    queryset = entries if entries is not None else StockEntry.objects.all()
    if ids == ():
        return queryset.none() if hasattr(queryset, "none") else []
    if not hasattr(queryset, "filter"):
        return [entry for entry in queryset if (ids is None or entry.department_id in ids) and entry.document.status == StockDocument.Status.POSTED]
    filters = {"document__status": StockDocument.Status.POSTED}
    if ids is not None:
        filters["department_id__in"] = ids
    return queryset.filter(**filters).select_related(
        "department", "warehouse", "location", "lot__item__unit", "lot__item__category", "unit", "funding_source", "document"
    )


def _kind(entry):
    kind = entry.document.document_type
    if kind == StockDocument.DocumentType.REVERSAL and entry.document.reverses_document_id:
        kind = entry.document.reverses_document.document_type
        return kind, True
    return kind, False


def _flow(entry):
    """Return (incoming, outgoing, neutral) for a signed journal entry."""
    kind, reversal = _kind(entry)
    quantity = abs(entry.quantity)
    if kind == StockDocument.DocumentType.RELOCATION:
        return ZERO, ZERO, quantity
    incoming_types = {StockDocument.DocumentType.OPENING, StockDocument.DocumentType.RECEIPT}
    outgoing_types = {StockDocument.DocumentType.ISSUE, StockDocument.DocumentType.WRITEOFF}
    if kind in incoming_types:
        incoming, outgoing = quantity, ZERO
    elif kind in outgoing_types:
        incoming, outgoing = ZERO, quantity
    elif kind == StockDocument.DocumentType.ADJUSTMENT:
        incoming, outgoing = (quantity, ZERO) if entry.quantity > 0 else (ZERO, quantity)
    else:
        incoming, outgoing = (quantity, ZERO) if entry.quantity > 0 else (ZERO, quantity)
    if reversal and kind != StockDocument.DocumentType.ADJUSTMENT:
        incoming, outgoing = outgoing, incoming
    return incoming, outgoing, ZERO


def _label(obj, fallback=""):
    return getattr(obj, "name", fallback) or fallback


def build_expense_report(*, department_ids, period_start: date, period_end: date, entries=None):
    """Build period movement rows from the immutable journal."""
    if period_end < period_start:
        raise ValueError("period_end must not precede period_start")
    source_entries = list(_entries(department_ids, entries))
    grouped = defaultdict(lambda: {"opening": ZERO, "incoming": ZERO, "outgoing": ZERO})
    samples = {}
    for entry in source_entries:
        if entry.operation_date > period_end:
            continue
        key = (entry.department_id, entry.lot.item_id, entry.funding_source_id, entry.unit_id)
        row = grouped[key]
        samples.setdefault(key, entry)
        incoming, outgoing, _ = _flow(entry)
        if entry.operation_date < period_start:
            row["opening"] += incoming - outgoing
        elif entry.operation_date <= period_end:
            row["incoming"] += incoming
            row["outgoing"] += outgoing
    result = []
    for (department_id, item_id, funding_id, unit_id), values in sorted(grouped.items()):
        sample = samples[(department_id, item_id, funding_id, unit_id)]
        result.append({
            "department_id": department_id, "department": _label(sample.department, str(department_id)),
            "item_id": item_id, "item": _label(sample.lot.item, str(item_id)),
            "funding_source_id": funding_id, "funding_source": _label(sample.funding_source, str(funding_id)),
            "unit_id": unit_id, "unit": _label(sample.unit, str(unit_id)),
            "opening": values["opening"], "incoming": values["incoming"], "outgoing": values["outgoing"],
            "closing": values["opening"] + values["incoming"] - values["outgoing"],
        })
    return result


def build_rack_card(*, department_ids, as_of: date, entries=None, include_zero=False):
    grouped = defaultdict(lambda: ZERO)
    samples = {}
    for entry in _entries(department_ids, entries):
        if entry.operation_date <= as_of:
            key = (entry.department_id, entry.warehouse_id, entry.location_id, entry.lot_id, entry.funding_source_id)
            grouped[key] += entry.quantity
            samples[key] = entry
    result = []
    for key in sorted(grouped):
        quantity = grouped[key]
        if not include_zero and quantity == ZERO:
            continue
        entry = samples[key]
        result.append({
            "department_id": entry.department_id, "department": _label(entry.department, str(entry.department_id)),
            "warehouse_id": entry.warehouse_id, "warehouse": _label(entry.warehouse, str(entry.warehouse_id)),
            "location_id": entry.location_id, "location": _label(entry.location, str(entry.location_id)), "location_code": entry.location.code,
            "item_id": entry.lot.item_id, "item": _label(entry.lot.item, str(entry.lot.item_id)),
            "batch_number": entry.lot.batch_number, "expires_on": entry.lot.expires_on,
            "unit": _label(entry.unit, str(entry.unit_id)), "funding_source": _label(entry.funding_source, str(entry.funding_source_id)),
            "category": _label(entry.lot.item.category), "dosage_form": entry.lot.item.dosage_form,
            "application_method": entry.lot.item.application_method, "quantity": quantity,
        })
    return result


def build_department_availability(*, department_ids, as_of: date, entries=None):
    card = build_rack_card(department_ids=department_ids, as_of=as_of, entries=entries, include_zero=True)
    grouped = defaultdict(lambda: ZERO)
    labels = {}
    for row in card:
        key = (row["department_id"], row["item_id"], row["unit"])
        grouped[key] += row["quantity"]
        labels[key] = row
    return [{"department_id": d, "department": labels[(d, i, u)]["department"], "item_id": i, "item": labels[(d, i, u)]["item"], "unit": u, "quantity": quantity}
            for (d, i, u), quantity in sorted(grouped.items()) if quantity != ZERO]
