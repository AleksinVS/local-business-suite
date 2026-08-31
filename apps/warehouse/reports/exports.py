from __future__ import annotations

import csv
import io
from decimal import Decimal


def _safe(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def export_csv(rows, *, fieldnames=None, metadata=None):
    rows = list(rows)
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

    rows = list(rows)
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
