from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from ..models import StockDocument, StockEntry

ZERO = Decimal("0")
REPORT_TOO_LARGE = "Слишком много строк для одного отчёта. Уточните фильтры."


class ReportTooLargeError(ValueError):
    """Raised before a report aggregate grows beyond its explicit row guard."""


def _entries(department_ids, entries=None, *, operation_date_lte=None):
    """Return posted entries in the caller-provided department scope."""
    ids = tuple(department_ids) if department_ids is not None else None
    queryset = entries if entries is not None else StockEntry.objects.all()
    if ids == ():
        return queryset.none() if hasattr(queryset, "none") else []
    if not hasattr(queryset, "filter"):
        return [entry for entry in queryset if (ids is None or entry.department_id in ids) and entry.document.status == StockDocument.Status.POSTED and (operation_date_lte is None or entry.operation_date <= operation_date_lte)]
    filters = {"document__status": StockDocument.Status.POSTED}
    if ids is not None:
        filters["department_id__in"] = ids
    if operation_date_lte is not None:
        filters["operation_date__lte"] = operation_date_lte
    return queryset.filter(**filters).select_related(
        "department",
        "warehouse",
        "location",
        "item__unit",
        "item__category",
        "unit",
        "funding_source",
        "document",
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


def _precision(entry):
    return int(getattr(getattr(entry, "unit", None), "quantity_precision", 0) or 0)


def _rack_key_sort_value(key):
    department_id, warehouse_id, location_id, item_id, series_key, expires_on, funding_id = key
    return (
        department_id,
        warehouse_id,
        location_id,
        item_id,
        series_key,
        expires_on is None,
        expires_on or date.max,
        funding_id,
    )


def build_expense_report(*, department_ids, period_start: date, period_end: date, entries=None, max_rows=None):
    """Build period movement rows from the immutable journal."""
    if period_end < period_start:
        raise ValueError("period_end must not precede period_start")
    source_entries = _entries(department_ids, entries, operation_date_lte=period_end)
    grouped = defaultdict(lambda: {"opening": ZERO, "incoming": ZERO, "outgoing": ZERO})
    samples = {}
    for entry in source_entries:
        if entry.operation_date > period_end:
            continue
        key = (entry.department_id, entry.item_id, entry.funding_source_id, entry.unit_id)
        if max_rows is not None and key not in grouped and len(grouped) >= max_rows:
            raise ReportTooLargeError(REPORT_TOO_LARGE)
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
            "item_id": item_id, "item": _label(sample.item, str(item_id)),
            "funding_source_id": funding_id, "funding_source": _label(sample.funding_source, str(funding_id)),
            "unit_id": unit_id, "unit": _label(sample.unit, str(unit_id)),
            "opening": values["opening"], "incoming": values["incoming"], "outgoing": values["outgoing"],
            "closing": values["opening"] + values["incoming"] - values["outgoing"],
            "quantity_precision": _precision(sample),
        })
    return result


def build_rack_card(*, department_ids, as_of: date, entries=None, include_zero=False, max_rows=None):
    grouped = defaultdict(lambda: ZERO)
    samples = {}
    for entry in _entries(department_ids, entries, operation_date_lte=as_of):
        if entry.operation_date <= as_of:
            key = (
                entry.department_id,
                entry.warehouse_id,
                entry.location_id,
                entry.item_id,
                entry.series_key,
                entry.expires_on,
                entry.funding_source_id,
            )
            if max_rows is not None and key not in grouped and len(grouped) >= max_rows:
                raise ReportTooLargeError(REPORT_TOO_LARGE)
            grouped[key] += entry.quantity
            samples[key] = entry
    result = []
    for key in sorted(grouped, key=_rack_key_sort_value):
        quantity = grouped[key]
        if not include_zero and quantity == ZERO:
            continue
        entry = samples[key]
        result.append({
            "department_id": entry.department_id, "department": _label(entry.department, str(entry.department_id)),
            "warehouse_id": entry.warehouse_id, "warehouse": _label(entry.warehouse, str(entry.warehouse_id)),
            "location_id": entry.location_id, "location": _label(entry.location, str(entry.location_id)), "location_code": entry.location.code,
            "item_id": entry.item_id, "item": _label(entry.item, str(entry.item_id)),
            "series": entry.series, "expires_on": entry.expires_on,
            "unit": _label(entry.unit, str(entry.unit_id)), "funding_source": _label(entry.funding_source, str(entry.funding_source_id)),
            "category": _label(entry.item.category), "dosage_form": entry.item.dosage_form,
            "application_method": entry.item.application_method, "quantity": quantity,
            "quantity_precision": _precision(entry),
            "location_purpose": getattr(entry.location, "purpose", "available"),
        })
    return result


def build_department_availability(*, department_ids, as_of: date, entries=None, max_rows=None):
    card = build_rack_card(department_ids=department_ids, as_of=as_of, entries=entries, include_zero=True, max_rows=max_rows)
    grouped = defaultdict(lambda: ZERO)
    labels = {}
    for row in card:
        key = (row["department_id"], row["item_id"], row["unit"], row.get("location_purpose", "available"))
        grouped[key] += row["quantity"]
        labels[key] = row
    return [{"department_id": d, "department": labels[(d, i, u, state)]["department"], "item_id": i, "item": labels[(d, i, u, state)]["item"], "unit": u, "quantity": quantity, "quantity_precision": labels[(d, i, u, state)]["quantity_precision"], "location_purpose": state}
            for (d, i, u, state), quantity in sorted(grouped.items()) if quantity != ZERO]
