from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


PARSER_VERSION = "source-text-extractor-v1"
PLAIN_TEXT_EXTENSIONS = {".txt", ".md", ".log", ".json", ".yaml", ".yml"}
DELIMITED_TEXT_EXTENSIONS = {".csv", ".tsv"}
SPREADSHEET_EXTENSIONS = {".xls", ".xlsx"}
SUPPORTED_SOURCE_TEXT_EXTENSIONS = PLAIN_TEXT_EXTENSIONS | DELIMITED_TEXT_EXTENSIONS | SPREADSHEET_EXTENSIONS

DEFAULT_MAX_TEXT_BYTES = 1_000_000
DEFAULT_MAX_SHEETS = 20
DEFAULT_MAX_ROWS = 5_000
DEFAULT_MAX_CELLS = 100_000
DEFAULT_MAX_CELL_CHARS = 2_000


@dataclass(frozen=True)
class TextExtractionLimits:
    max_text_bytes: int = DEFAULT_MAX_TEXT_BYTES
    max_sheets: int = DEFAULT_MAX_SHEETS
    max_rows: int = DEFAULT_MAX_ROWS
    max_cells: int = DEFAULT_MAX_CELLS
    max_cell_chars: int = DEFAULT_MAX_CELL_CHARS


@dataclass(frozen=True)
class ExtractedSourceText:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    partial: bool = False
    partial_reason: str = ""


class TextExtractionError(ValueError):
    def __init__(self, message: str, *, issue_kind: str = "unsupported_format", metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.issue_kind = issue_kind
        self.metadata = metadata or {}


def extract_text_from_file(path: Path, *, limits: TextExtractionLimits | None = None) -> ExtractedSourceText:
    limits = limits or TextExtractionLimits()
    extension = path.suffix.lower()
    if extension in PLAIN_TEXT_EXTENSIONS:
        return _extract_plain_text(path, limits=limits)
    if extension in DELIMITED_TEXT_EXTENSIONS:
        return _extract_delimited_text(path, limits=limits, delimiter="\t" if extension == ".tsv" else ",")
    if extension in SPREADSHEET_EXTENSIONS:
        return _extract_spreadsheet_text(path, limits=limits)
    raise TextExtractionError(f"Unsupported extension: {extension or '<none>'}")


def extraction_limits_from_settings() -> TextExtractionLimits:
    try:
        from django.conf import settings

        payload = getattr(settings, "LOCAL_BUSINESS_MEMORY_TEXT_EXTRACTION_LIMITS", {}) or {}
    except Exception:
        payload = {}
    return TextExtractionLimits(
        max_text_bytes=_positive_int(payload.get("max_text_bytes"), DEFAULT_MAX_TEXT_BYTES),
        max_sheets=_positive_int(payload.get("max_sheets"), DEFAULT_MAX_SHEETS),
        max_rows=_positive_int(payload.get("max_rows"), DEFAULT_MAX_ROWS),
        max_cells=_positive_int(payload.get("max_cells"), DEFAULT_MAX_CELLS),
        max_cell_chars=_positive_int(payload.get("max_cell_chars"), DEFAULT_MAX_CELL_CHARS),
    )


def _extract_plain_text(path: Path, *, limits: TextExtractionLimits) -> ExtractedSourceText:
    data = path.read_bytes()
    partial = len(data) > limits.max_text_bytes
    if partial:
        data = data[: limits.max_text_bytes]
    text = _normalise_search_text(data.decode("utf-8", errors="replace"), max_chars=limits.max_text_bytes)
    return ExtractedSourceText(
        text=text,
        metadata={
            "parser": PARSER_VERSION,
            "format": path.suffix.lower().lstrip("."),
            "text_bytes": len(text.encode("utf-8", errors="ignore")),
        },
        partial=partial,
        partial_reason="Extracted text exceeded byte limit." if partial else "",
    )


def _extract_delimited_text(path: Path, *, limits: TextExtractionLimits, delimiter: str) -> ExtractedSourceText:
    data = path.read_bytes()
    decoded = data[: limits.max_text_bytes].decode("utf-8-sig", errors="replace")
    lines = []
    rows_seen = 0
    cells_seen = 0
    partial = len(data) > limits.max_text_bytes
    reader = csv.reader(decoded.splitlines(), delimiter=delimiter)
    for row in reader:
        if rows_seen >= limits.max_rows or cells_seen >= limits.max_cells:
            partial = True
            break
        rows_seen += 1
        safe_row = []
        for cell in row:
            if cells_seen >= limits.max_cells:
                partial = True
                break
            cells_seen += 1
            value = _cell_to_text(cell, max_chars=limits.max_cell_chars)
            if value:
                safe_row.append(value)
        if safe_row:
            lines.append(" | ".join(safe_row))
        if _text_bytes(lines) >= limits.max_text_bytes:
            partial = True
            break
    text = _normalise_search_text("\n".join(lines), max_chars=limits.max_text_bytes)
    return ExtractedSourceText(
        text=text,
        metadata={
            "parser": PARSER_VERSION,
            "format": path.suffix.lower().lstrip("."),
            "rows_seen": rows_seen,
            "cells_seen": cells_seen,
            "text_bytes": len(text.encode("utf-8", errors="ignore")),
        },
        partial=partial,
        partial_reason="Delimited text extraction reached configured limits." if partial else "",
    )


def _extract_spreadsheet_text(path: Path, *, limits: TextExtractionLimits) -> ExtractedSourceText:
    try:
        from python_calamine import CalamineError, PasswordError, load_workbook
    except ImportError as exc:
        raise TextExtractionError(
            "python-calamine is required to extract .xls/.xlsx text.",
            issue_kind="unsupported_format",
            metadata={"missing_dependency": "python-calamine"},
        ) from exc

    try:
        workbook = load_workbook(str(path))
    except PasswordError as exc:
        raise TextExtractionError("Encrypted spreadsheet was skipped.", issue_kind="encrypted_file") from exc
    except CalamineError as exc:
        raise TextExtractionError(f"Spreadsheet parser failed: {exc}", issue_kind="unsupported_format") from exc

    lines: list[str] = []
    sheet_names: list[str] = []
    rows_seen = 0
    cells_seen = 0
    partial = False
    try:
        for sheet_index, sheet_name in enumerate(list(workbook.sheet_names or [])):
            if sheet_index >= limits.max_sheets:
                partial = True
                break
            sheet = workbook.get_sheet_by_name(sheet_name)
            sheet_names.append(str(sheet_name))
            lines.append(f"Sheet: {_cell_to_text(sheet_name, max_chars=limits.max_cell_chars)}")
            for row in sheet.iter_rows():
                if rows_seen >= limits.max_rows or cells_seen >= limits.max_cells:
                    partial = True
                    break
                rows_seen += 1
                safe_row = []
                for cell in row:
                    if cells_seen >= limits.max_cells:
                        partial = True
                        break
                    cells_seen += 1
                    value = _cell_to_text(cell, max_chars=limits.max_cell_chars)
                    if value:
                        safe_row.append(value)
                if safe_row:
                    lines.append(" | ".join(safe_row))
                if _text_bytes(lines) >= limits.max_text_bytes:
                    partial = True
                    break
            if partial:
                break
    finally:
        close = getattr(workbook, "close", None)
        if callable(close):
            close()

    text = _normalise_search_text("\n".join(lines), max_chars=limits.max_text_bytes)
    return ExtractedSourceText(
        text=text,
        metadata={
            "parser": PARSER_VERSION,
            "format": path.suffix.lower().lstrip("."),
            "sheet_names": sheet_names,
            "sheet_count": len(sheet_names),
            "rows_seen": rows_seen,
            "cells_seen": cells_seen,
            "text_bytes": len(text.encode("utf-8", errors="ignore")),
        },
        partial=partial,
        partial_reason="Spreadsheet extraction reached configured limits." if partial else "",
    )


def _cell_to_text(value: Any, *, max_chars: int) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    text = _normalise_whitespace(text)
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _normalise_search_text(text: str, *, max_chars: int) -> str:
    lines = [_normalise_whitespace(line) for line in str(text or "").splitlines()]
    compact = "\n".join(line for line in lines if line)
    if len(compact.encode("utf-8", errors="ignore")) <= max_chars:
        return compact
    encoded = compact.encode("utf-8", errors="ignore")[:max_chars]
    return encoded.decode("utf-8", errors="ignore")


def _normalise_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _text_bytes(lines: Iterable[str]) -> int:
    return len("\n".join(lines).encode("utf-8", errors="ignore"))


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


__all__ = [
    "ExtractedSourceText",
    "PARSER_VERSION",
    "SUPPORTED_SOURCE_TEXT_EXTENSIONS",
    "TextExtractionError",
    "TextExtractionLimits",
    "extract_text_from_file",
    "extraction_limits_from_settings",
]
