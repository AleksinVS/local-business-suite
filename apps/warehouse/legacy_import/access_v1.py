"""Первый профиль отображения обследованной Access-базы склада.

Таблицы и alias-поля живут в домене. Общий ACE transport получает лишь список
таблиц и никогда не импортирует эти знания.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation


ACCESS_V1_ADAPTER = "access-v1"
TRANSFORMATION_VERSION = "access-v1.0"
TABLES = ("istoch", "s_ls", "s_otdelenie", "Sklad", "stelazh", "uchet")
INTENTIONALLY_SKIPPED_TABLES = ("sett", "tmp", "treb")
SECRET_COLUMN_NAMES = {"pass", "password", "pwd", "secret", "token"}


def canonical_column_map(payload: dict) -> dict[str, object]:
    return {str(key).strip().casefold(): value for key, value in (payload or {}).items()}


def value_from(payload: dict, *aliases: str) -> object:
    indexed = canonical_column_map(payload)
    for alias in aliases:
        value = indexed.get(alias.casefold())
        if value not in (None, ""):
            return value
    return ""


def text_from(payload: dict, *aliases: str) -> str:
    return str(value_from(payload, *aliases) or "").strip()


def decimal_from(payload: dict, *aliases: str) -> Decimal | None:
    value = value_from(payload, *aliases)
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def date_from(payload: dict, *aliases: str) -> date | None:
    value = value_from(payload, *aliases)
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text[:10],):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def funding_dto(payload: dict) -> dict:
    return {
        "legacy_key": text_from(payload, "id", "kod", "code", "id_istoch"),
        "code": text_from(payload, "kod", "code", "id", "id_istoch"),
        "name": text_from(payload, "name", "naimenovanie", "istoch", "name_istoch"),
    }


def item_dto(payload: dict) -> dict:
    return {
        "legacy_key": text_from(payload, "id", "kod", "code", "id_ls"),
        "code": text_from(payload, "kod", "code", "id", "id_ls"),
        "name": text_from(payload, "name", "naimenovanie", "naim", "ls_name"),
        "unit": text_from(payload, "unit", "ed", "ed_izm", "edinica", "edizm"),
        "manufacturer": text_from(payload, "manufacturer", "proizvoditel"),
        "dosage_form": text_from(payload, "dosage_form", "forma"),
        "application_method": text_from(payload, "application_method", "sposob_primeneniya"),
    }


def department_dto(payload: dict) -> dict:
    return {
        "legacy_key": text_from(payload, "id", "kod", "code", "id_otd"),
        "name": text_from(payload, "otd_name", "name", "naimenovanie", "department"),
    }


def opening_stock_dto(payload: dict) -> dict:
    """Нормализовать начальный остаток по серии без угадывания адреса."""
    return {
        "legacy_key": text_from(payload, "id", "kod", "code"),
        "department": text_from(payload, "otd_name", "department", "otdelenie"),
        "item_code": text_from(
            payload,
            "item_code",
            "ls_code",
            "kod_ls",
            "code_ls",
            "id_ls",
        ),
        "item_name": text_from(
            payload,
            "item",
            "item_name",
            "name",
            "naimenovanie",
            "ls_name",
        ),
        "unit": text_from(payload, "unit", "ed", "ed_izm", "edinica", "edizm"),
        "funding_source_code": text_from(
            payload,
            "funding_source_code",
            "source_code",
            "istoch_code",
            "kod_istoch",
            "code_istoch",
            "id_istoch",
        ),
        "funding_source_name": text_from(
            payload,
            "istoch",
            "funding_source",
            "funding_source_name",
            "source",
            "source_name",
            "name_istoch",
        ),
        "quantity": decimal_from(payload, "quantity", "kol", "kolvo", "ostatok"),
        "series": text_from(payload, "batch", "series", "seria", "nomer_serii"),
        "expires_on": date_from(payload, "expires_on", "expiry", "srok_godnosti"),
        "application_method": text_from(payload, "application_method", "sposob_primeneniya"),
    }
