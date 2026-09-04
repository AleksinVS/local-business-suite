from __future__ import annotations

import csv
import io
from decimal import Decimal

REPORT_COLUMN_LABELS = {
    "department": "Подразделение", "item": "Наименование", "funding_source": "Источник финансирования",
    "unit": "Единица измерения", "opening": "Остаток на начало", "incoming": "Поступило",
    "outgoing": "Отпущено", "closing": "Остаток на конец", "warehouse": "Склад", "location": "Адрес хранения",
    "location_code": "Код адреса", "series": "Серия", "expires_on": "Срок годности", "category": "Категория",
    "dosage_form": "Форма выпуска", "application_method": "Способ применения", "quantity": "Остаток",
    "location_purpose": "Состояние адреса",
}

LOCATION_PURPOSE_LABELS = {"available": "Доступно", "quarantine": "Карантин", "unassigned": "Адрес не назначен"}


def format_quantity(value, precision=0):
    """Format a quantity according to the unit precision without float conversion."""
    if value is None:
        return ""
    number = Decimal(str(value))
    return f"{number:.{max(0, int(precision or 0))}f}"


def report_fieldnames(rows):
    fields = list(rows[0].keys()) if rows else []
    return [field for field in fields if not field.endswith("_id") and field != "quantity_precision"]


def user_fieldnames(rows):
    return [REPORT_COLUMN_LABELS.get(field, field) for field in report_fieldnames(rows)]


def prepare_export_rows(rows):
    prepared = []
    fields = report_fieldnames(rows)
    for row in rows:
        item = {}
        for field in fields:
            value = row.get(field)
            if field in {"quantity", "opening", "incoming", "outgoing", "closing"}:
                value = format_quantity(value, row.get("quantity_precision", 0))
            elif hasattr(value, "isoformat"):
                value = value.isoformat()
            elif field == "location_purpose":
                value = LOCATION_PURPOSE_LABELS.get(value, value)
            item[REPORT_COLUMN_LABELS.get(field, field)] = value
        prepared.append(item)
    return prepared


def _safe(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def export_csv(rows, *, fieldnames=None, metadata=None):
    rows = list(rows)
    rows = prepare_export_rows(rows)
    fieldnames = list(fieldnames or (rows[0].keys() if rows else []))
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    for key, value in (metadata or {}).items():
        writer.writerow([_safe(key), _safe(value)])
    if metadata:
        writer.writerow([])
    writer.writerow(fieldnames)
    for row in rows:
        writer.writerow([_safe(row.get(field)) for field in fieldnames])
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def export_xlsx(rows, *, fieldnames=None, sheet_name="Отчёт", metadata=None):
    import xlsxwriter

    rows = prepare_export_rows(list(rows))
    fieldnames = list(fieldnames or (rows[0].keys() if rows else []))
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    sheet = workbook.add_worksheet(sheet_name[:31])
    row_offset = 0
    for key, value in (metadata or {}).items():
        sheet.write_string(row_offset, 0, _safe(key))
        sheet.write_string(row_offset, 1, _safe(value))
        row_offset += 1
    if metadata:
        row_offset += 1
    for column, field in enumerate(fieldnames):
        sheet.write_string(row_offset, column, _safe(field))
    for row_index, row in enumerate(rows, row_offset + 1):
        for column, field in enumerate(fieldnames):
            value = row.get(field)
            if isinstance(value, Decimal):
                value = format(value, "f")
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            sheet.write_string(row_index, column, _safe(value))
    workbook.close()
    return output.getvalue()
