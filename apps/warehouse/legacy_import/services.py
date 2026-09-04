"""Подготовка, идемпотентный импорт и сверка landing package склада.

Этот модуль намеренно не пишет ``StockEntry`` или ``StockBalance`` напрямую.
Начальные остатки по сериям передаются только в доменный posting service, когда
тот доступен; до этого commit закрыто отклоняется.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.integrations.ace_legacy import run_access_export
from apps.core.models import Department
from apps.warehouse.models import (
    FundingSource,
    StockDocument,
    StockDocumentLine,
    StockBalance,
    StockEntry,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
    WarehouseAuditEvent,
    WarehouseImportIssue,
    WarehouseImportRecord,
    WarehouseImportRun,
    WarehouseItem,
    WarehouseItemCategory,
)
from apps.warehouse.series import normalize_series

from .access_v1 import (
    ACCESS_V1_ADAPTER,
    INTENTIONALLY_SKIPPED_TABLES,
    TABLES,
    TRANSFORMATION_VERSION,
    department_dto,
    funding_dto,
    item_dto,
    opening_stock_dto,
)
from .landing import LandingPackageError, load_landing_package, package_dir, sha256_payload, write_landing_package


class LegacyImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedIssue:
    severity: str
    code: str
    message: str
    source_table: str = ""
    legacy_key: str = ""
    context: dict | None = None


@dataclass(frozen=True)
class _CatalogIdentity:
    row: dict
    dto: dict
    target_code: str


def _identity_key(value: object) -> str:
    return str(value or "").strip().casefold()


def _catalog_identities(
    *, rows: dict[str, list[dict]], table: str, dto_factory, prefix: str
) -> list[_CatalogIdentity]:
    identities = []
    for row in rows.get(table, []):
        dto = dto_factory(row.get("payload", {}))
        identities.append(
            _CatalogIdentity(
                row=row,
                dto=dto,
                target_code=_stable_code(prefix, dto["code"] or dto["name"]),
            )
        )
    return identities


def _item_identities(rows: dict[str, list[dict]]) -> list[_CatalogIdentity]:
    return _catalog_identities(
        rows=rows,
        table="s_ls",
        dto_factory=item_dto,
        prefix="legacy-item",
    )


def _source_identities(rows: dict[str, list[dict]]) -> list[_CatalogIdentity]:
    return _catalog_identities(
        rows=rows,
        table="istoch",
        dto_factory=funding_dto,
        prefix="legacy-source",
    )


def _resolve_catalog_identity(
    identities: list[_CatalogIdentity],
    *,
    reference_code: str,
    reference_name: str,
) -> tuple[str | None, str]:
    """Resolve an explicit code first, otherwise an unambiguous display name."""

    if reference_code:
        code_key = _identity_key(reference_code)
        candidates = {
            identity.target_code
            for identity in identities
            if code_key
            in {
                _identity_key(identity.dto["code"]),
                _identity_key(identity.dto["legacy_key"]),
            }
        }
    elif reference_name:
        name_key = _identity_key(reference_name)
        candidates = {
            identity.target_code
            for identity in identities
            if _identity_key(identity.dto["name"]) == name_key
        }
    else:
        return None, "missing"
    if len(candidates) == 1:
        return next(iter(candidates)), "resolved"
    if candidates:
        return None, "ambiguous"
    return None, "missing"


def _resolve_opening_item(
    dto: dict, identities: list[_CatalogIdentity]
) -> tuple[str | None, str]:
    return _resolve_catalog_identity(
        identities,
        reference_code=dto["item_code"],
        reference_name=dto["item_name"],
    )


def _resolve_opening_source(
    dto: dict, identities: list[_CatalogIdentity]
) -> tuple[str | None, str]:
    return _resolve_catalog_identity(
        identities,
        reference_code=dto["funding_source_code"],
        reference_name=dto["funding_source_name"],
    )


def _catalog_identity_collisions(
    identities: list[_CatalogIdentity],
) -> list[dict]:
    by_target: dict[str, set[tuple[str, str]]] = {}
    for identity in identities:
        signature = (
            _identity_key(identity.dto["code"]),
            _identity_key(identity.dto["name"]),
        )
        by_target.setdefault(identity.target_code, set()).add(signature)
    return [
        {"target_code": target_code, "identities": sorted(signatures)}
        for target_code, signatures in sorted(by_target.items())
        if len(signatures) > 1
    ]


def load_mapping(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyImportError("Не удалось прочитать JSON сопоставлений.") from exc
    if not isinstance(payload, dict):
        raise LegacyImportError("Сопоставления должны быть JSON-объектом.")
    return payload


def extract_access_landing(*, run_id: str, source: Path, requested_dir: Path | None = None, sample_size: int = 5) -> tuple[Path, dict]:
    """Выгрузить Access через общий transport и запечатать профильный пакет."""
    target = package_dir(run_id, requested=requested_dir)
    transport_dir = target / "transport"
    transport_manifest = run_access_export(
        source=source,
        output_dir=transport_dir,
        tables=TABLES,
        sample_size=sample_size,
        inspect_only=False,
    )
    if transport_manifest.get("source_changed_during_extract"):
        raise LegacyImportError("Источник изменился во время read-only выгрузки.")
    tables = {}
    schema = {}
    for table in transport_manifest.get("tables", []):
        name = table.get("name")
        relative_path = table.get("file")
        if name not in TABLES or not relative_path:
            continue
        rows_path = transport_dir / relative_path
        try:
            rows = [json.loads(line).get("payload", {}) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError) as exc:
            raise LegacyImportError(f"Некорректная JSONL-выгрузка таблицы {name}.") from exc
        tables[name] = rows
        schema[name] = {"columns": table.get("columns", []), "indexes": table.get("indexes", [])}
    return write_landing_package(
        run_id=run_id,
        source_fingerprint=str(transport_manifest.get("source_fingerprint") or ""),
        source_name=str(transport_manifest.get("source_name") or source.name),
        adapter=ACCESS_V1_ADAPTER,
        transformation_version=TRANSFORMATION_VERSION,
        tables=tables,
        schema=schema,
        requested_dir=target,
    )


def ensure_import_run(*, manifest: dict) -> WarehouseImportRun:
    run_id = uuid.UUID(manifest["run_id"])
    existing_source_run = WarehouseImportRun.objects.filter(
        source_fingerprint=manifest["source_fingerprint"],
        adapter=manifest["adapter"],
        transformation_version=manifest["transformation_version"],
    ).first()
    if existing_source_run is not None and existing_source_run.run_id != run_id:
        raise LegacyImportError(
            "Этот источник и профиль уже зарегистрированы в другом запуске: "
            f"{existing_source_run.run_id}. Повторите операцию с исходным run-id."
        )
    defaults = {
        "source_fingerprint": manifest["source_fingerprint"],
        "source_name": manifest.get("source_name", ""),
        "adapter": manifest["adapter"],
        "transformation_version": manifest["transformation_version"],
        "manifest": manifest,
    }
    run, created = WarehouseImportRun.objects.get_or_create(run_id=run_id, defaults=defaults)
    if not created:
        expected = (manifest["source_fingerprint"], manifest["adapter"], manifest["transformation_version"])
        actual = (run.source_fingerprint, run.adapter, run.transformation_version)
        if expected != actual:
            raise LegacyImportError("run-id уже привязан к другому источнику или профилю.")
    return run


def prepare_landing(
    *, run_id: str, mapping: dict | None = None, include_unused_catalog: bool = False,
    requested_dir: Path | None = None,
) -> tuple[WarehouseImportRun, dict, list[PreparedIssue]]:
    _, manifest, rows = load_landing_package(run_id, requested_dir=requested_dir)
    if manifest.get("adapter") != ACCESS_V1_ADAPTER:
        raise LegacyImportError("Для этого landing package не найден профиль Access v1.")
    run = ensure_import_run(manifest=manifest)
    mapping = mapping or {}
    issues = _validate_rows(
        rows=rows,
        mapping=mapping,
        include_unused_catalog=include_unused_catalog,
        existing_series_expiries=_existing_series_expiries(rows),
    )
    _sync_issues(run=run, issues=issues)
    run.manifest = {
        **manifest,
        "mapping_sha256": sha256_payload(mapping),
        "mapping": mapping,
        "include_unused_catalog": include_unused_catalog,
        "prepared_at": timezone.now().isoformat(),
    }
    run.status = WarehouseImportRun.Status.PREPARED
    run.save(update_fields=["manifest", "status"])
    summary = {
        "run_id": str(run.run_id),
        "critical_issues": sum(issue.severity == WarehouseImportIssue.Severity.CRITICAL for issue in issues),
        "warning_issues": sum(issue.severity == WarehouseImportIssue.Severity.WARNING for issue in issues),
        "planned": {table: len(values) for table, values in rows.items()},
        "intentionally_skipped": list(INTENTIONALLY_SKIPPED_TABLES) + ["s_otdelenie.pass"],
    }
    return run, summary, issues


def _validate_rows(
    *,
    rows: dict[str, list[dict]],
    mapping: dict,
    include_unused_catalog: bool = False,
    existing_series_expiries: dict[tuple[str, str], set[date | None]] | None = None,
) -> list[PreparedIssue]:
    issues: list[PreparedIssue] = []
    department_map = _normalised_mapping(mapping.get("departments"))
    unit_map = _normalised_mapping(mapping.get("units"))
    item_identities = _item_identities(rows)
    source_identities = _source_identities(rows)
    for record in rows.get("s_otdelenie", []):
        dto = department_dto(record.get("payload", {}))
        if not dto["name"]:
            issues.append(_issue("critical", "department_name_missing", "Не указано название подразделения.", "s_otdelenie", dto["legacy_key"]))
        elif dto["name"].casefold() not in department_map:
            issues.append(_issue("critical", "department_mapping_missing", "Нет подтверждённого сопоставления подразделения.", "s_otdelenie", dto["legacy_key"], {"legacy_name": dto["name"]}))
    for record in rows.get("istoch", []):
        dto = funding_dto(record.get("payload", {}))
        if not dto["name"]:
            issues.append(_issue("critical", "funding_source_name_missing", "Не указано наименование источника финансирования.", "istoch", dto["legacy_key"]))
    for collision in _catalog_identity_collisions(source_identities):
        issues.append(
            _issue(
                "critical",
                "funding_source_identity_collision",
                "Несколько legacy-источников образуют один целевой код.",
                "istoch",
                context=collision,
            )
        )
    for record in _catalog_rows(rows=rows, include_unused_catalog=include_unused_catalog):
        dto = item_dto(record.get("payload", {}))
        if not dto["name"]:
            issues.append(_issue("critical", "item_name_missing", "Не указано наименование складской позиции.", "s_ls", dto["legacy_key"]))
        if not dto["unit"] or dto["unit"].casefold() not in unit_map:
            issues.append(_issue("critical", "unit_mapping_missing", "Нет подтверждённого сопоставления единицы измерения.", "s_ls", dto["legacy_key"], {"legacy_unit": dto["unit"]}))
    for collision in _catalog_identity_collisions(item_identities):
        issues.append(
            _issue(
                "critical",
                "item_identity_collision",
                "Несколько legacy-позиций образуют один целевой код.",
                "s_ls",
                context=collision,
            )
        )
    seen_hashes: set[tuple[str, str]] = set()
    for table, table_rows in rows.items():
        for record in table_rows:
            key = (table, str(record.get("row_hash") or ""))
            if key in seen_hashes:
                issues.append(_issue("critical", "ambiguous_duplicate_source_row", "В landing package есть неразличимые строки.", table, key[1]))
            seen_hashes.add(key)
    expiry_by_series: dict[tuple[str, str], set[date | None]] = {}
    series_records: dict[tuple[str, str], list[tuple[dict, dict]]] = {}
    for record in rows.get("stelazh", []):
        dto = opening_stock_dto(record.get("payload", {}))
        if dto["quantity"] is None or dto["quantity"] <= 0:
            issues.append(_issue("critical", "opening_quantity_invalid", "Начальный остаток имеет некорректное количество.", "stelazh", dto["legacy_key"]))
        if dto["department"].casefold() not in department_map:
            issues.append(_issue("critical", "opening_department_mapping_missing", "Нет подтверждённого подразделения начального остатка.", "stelazh", dto["legacy_key"]))
        if dto["unit"].casefold() not in unit_map:
            issues.append(_issue("critical", "opening_unit_mapping_missing", "Нет подтверждённой единицы начального остатка.", "stelazh", dto["legacy_key"]))
        item_target_code, item_status = _resolve_opening_item(dto, item_identities)
        if item_status != "resolved":
            issue_code = (
                "opening_item_ambiguous"
                if item_status == "ambiguous"
                else "opening_item_missing"
            )
            issues.append(
                _issue(
                    "critical",
                    issue_code,
                    "Серия ссылается на неоднозначную позицию."
                    if item_status == "ambiguous"
                    else "Серия ссылается на нераспознанную позицию.",
                    "stelazh",
                    dto["legacy_key"],
                    {
                        "item_code": dto["item_code"],
                        "item_name": dto["item_name"],
                    },
                )
            )
        _source_target_code, source_status = _resolve_opening_source(
            dto, source_identities
        )
        if source_status != "resolved":
            issue_code = (
                "opening_funding_source_ambiguous"
                if source_status == "ambiguous"
                else "opening_funding_source_missing"
            )
            issues.append(
                _issue(
                    "critical",
                    issue_code,
                    "Серия ссылается на неоднозначный источник финансирования."
                    if source_status == "ambiguous"
                    else "Серия ссылается на нераспознанный источник финансирования.",
                    "stelazh",
                    dto["legacy_key"],
                    {
                        "funding_source_code": dto["funding_source_code"],
                        "funding_source_name": dto["funding_source_name"],
                    },
                )
            )
        _, series_key = normalize_series(dto["series"])
        if series_key and item_target_code:
            key = (item_target_code, series_key)
            expiry_by_series.setdefault(key, set()).add(dto["expires_on"])
            series_records.setdefault(key, []).append((record, dto))
    for key, expiries in expiry_by_series.items():
        item_target_code, series_key = key
        existing_expiries = set((existing_series_expiries or {}).get(key, set()))
        all_expiries = expiries | existing_expiries
        if len(all_expiries) <= 1:
            continue
        expiry_labels = sorted(
            (value.isoformat() if value else None for value in all_expiries),
            key=lambda value: (value is None, value or ""),
        )
        for _, dto in series_records[key]:
            issues.append(
                _issue(
                    "critical",
                    "series_expiry_conflict",
                    "Одна серия позиции имеет разные сроки годности; значение не угадано.",
                    "stelazh",
                    dto["legacy_key"],
                    {
                        "item_code": item_target_code,
                        "item_name": dto["item_name"],
                        "series_key": series_key,
                        "expires_on": expiry_labels,
                    },
                )
            )
    if rows.get("stelazh") and not _opening_date(mapping):
        issues.append(_issue("critical", "opening_date_missing", "Для начальных остатков требуется явно заданная дата среза opening_date."))
    if rows.get("uchet"):
        issues.append(
            _issue(
                "critical",
                "uchet_history_requires_balance_review",
                "История uchet не импортируется, пока отдельная балансная проверка не подтверждена.",
                "uchet",
            )
        )
    return issues


def _existing_series_expiries(rows):
    result: dict[tuple[str, str], set[date | None]] = {}
    item_identities = _item_identities(rows)
    for record in rows.get("stelazh", []):
        dto = opening_stock_dto(record.get("payload", {}))
        _, series_key = normalize_series(dto["series"])
        item_code, status = _resolve_opening_item(dto, item_identities)
        if status != "resolved" or not item_code or not series_key:
            continue
        item = WarehouseItem.objects.filter(code=item_code).first()
        if item is None:
            continue
        result[(item_code, series_key)] = set(
            StockEntry.objects.filter(item=item, series_key=series_key).values_list(
                "expires_on", flat=True
            )
        )
    return result


def _issue(severity: str, code: str, message: str, table: str = "", legacy_key: str = "", context: dict | None = None) -> PreparedIssue:
    return PreparedIssue(severity, code, message, table, legacy_key, context or {})


def _normalised_mapping(value: object) -> dict[str, object]:
    return {str(key).strip().casefold(): target for key, target in (value or {}).items() if str(key).strip()}


def _sync_issues(*, run: WarehouseImportRun, issues: list[PreparedIssue]) -> None:
    for issue in issues:
        WarehouseImportIssue.objects.get_or_create(
            run=run,
            severity=issue.severity,
            code=issue.code,
            source_table=issue.source_table,
            legacy_key=issue.legacy_key,
            defaults={"message": issue.message, "context": issue.context or {}},
        )


def import_landing(
    *, run_id: str, mapping: dict | None = None, commit: bool = False, actor=None,
    include_unused_catalog: bool = False, requested_dir: Path | None = None,
) -> dict:
    """Подготовить либо применить каталог; начальные остатки — через posting API."""
    run, summary, issues = prepare_landing(
        run_id=run_id, mapping=mapping, include_unused_catalog=include_unused_catalog,
        requested_dir=requested_dir,
    )
    if not commit:
        return {"ok": not summary["critical_issues"], "dry_run": True, **summary}
    if summary["critical_issues"] or run.issues.filter(severity=WarehouseImportIssue.Severity.CRITICAL, resolved_at__isnull=True).exists():
        raise LegacyImportError("Commit запрещён: есть неразрешённые критические проблемы импорта.")
    if actor is None:
        raise LegacyImportError("Для --commit укажите активного оператора --actor.")
    from apps.warehouse.policies import require_warehouse_catalog_access

    require_warehouse_catalog_access(actor=actor)
    _, _, rows = load_landing_package(run_id, requested_dir=requested_dir)
    with transaction.atomic():
        run.created_by = actor
        run.save(update_fields=["created_by"])
        WarehouseAuditEvent.objects.create(
            actor=actor,
            action="legacy_import.started",
            object_type="WarehouseImportRun",
            object_id=str(run.run_id),
            summary={
                "adapter": run.adapter,
                "source_fingerprint": run.source_fingerprint,
            },
        )
        catalog = _import_catalog(
            run=run, rows=rows, mapping=mapping or {}, include_unused_catalog=include_unused_catalog
        )
        if rows.get("stelazh"):
            _post_opening_series_via_domain_service(
                run=run, rows=rows, mapping=mapping or {}, actor=actor
            )
        run.status = WarehouseImportRun.Status.IMPORTED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])
        WarehouseAuditEvent.objects.create(
            actor=actor,
            action="legacy_import.completed",
            object_type="WarehouseImportRun",
            object_id=str(run.run_id),
            summary={"catalog": catalog, "opening_rows": len(rows.get("stelazh", []))},
        )
    return {"ok": True, "dry_run": False, **summary, "catalog": catalog}


def _import_catalog(
    *, run: WarehouseImportRun, rows: dict[str, list[dict]], mapping: dict,
    include_unused_catalog: bool,
) -> dict[str, int]:
    unit_map = _normalised_mapping(mapping.get("units"))
    created = {"funding_sources": 0, "units": 0, "items": 0}
    category, _ = WarehouseItemCategory.objects.get_or_create(
        code="legacy-uncategorized", defaults={"name": "Импортировано из legacy"}
    )
    for row in rows.get("istoch", []):
        dto = funding_dto(row["payload"])
        code = _stable_code("legacy-source", dto["code"] or dto["name"])
        source, was_created = FundingSource.objects.get_or_create(code=code, defaults={"name": dto["name"]})
        created["funding_sources"] += int(was_created)
        _record(run, "istoch", row, source, "created" if was_created else "reused")
    for row in _catalog_rows(rows=rows, include_unused_catalog=include_unused_catalog):
        dto = item_dto(row["payload"])
        mapped_unit = str(unit_map.get(dto["unit"].casefold()) or "").strip()
        unit_code = _stable_code("legacy-unit", mapped_unit)
        unit, was_created = UnitOfMeasure.objects.get_or_create(code=unit_code, defaults={"name": mapped_unit, "quantity_precision": 0})
        created["units"] += int(was_created)
        item_code = _stable_code("legacy-item", dto["code"] or dto["name"])
        item, item_created = WarehouseItem.objects.get_or_create(
            code=item_code,
            defaults={
                "name": dto["name"], "short_name": dto["name"][:255], "category": category, "unit": unit,
                "manufacturer": dto["manufacturer"], "dosage_form": dto["dosage_form"], "application_method": dto["application_method"],
            },
        )
        created["items"] += int(item_created)
        _record(run, "s_ls", row, item, "created" if item_created else "reused")
    return created


def _catalog_rows(*, rows: dict[str, list[dict]], include_unused_catalog: bool) -> list[dict]:
    if include_unused_catalog:
        return rows.get("s_ls", [])
    identities = _item_identities(rows)
    referenced_codes = set()
    for table in ("stelazh", "uchet"):
        for record in rows.get(table, []):
            dto = opening_stock_dto(record.get("payload", {}))
            target_code, status = _resolve_opening_item(dto, identities)
            if status == "resolved" and target_code:
                referenced_codes.add(target_code)
    return [
        identity.row
        for identity in identities
        if identity.target_code in referenced_codes
    ]


def _record(run, table: str, row: dict, target, result: str) -> None:
    WarehouseImportRecord.objects.get_or_create(
        run=run,
        source_table=table,
        row_hash=row["row_hash"],
        defaults={
            "legacy_key": str((row.get("source_identity") or {}).get("value") or "")[:255],
            "target_model": target._meta.label,
            "target_pk": str(target.pk),
            "result": result,
        },
    )


def _stable_code(prefix: str, value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-")
    if not normalized:
        normalized = sha256_payload(value)[:12]
    return f"{prefix}-{normalized}"[:64]


def _post_opening_series_via_domain_service(*, run, rows, mapping, actor) -> None:
    """Создать начальные документы и провести их исключительно через posting API."""
    from apps.warehouse.services.posting import post_document

    opening_date = _opening_date(mapping)
    if opening_date is None:
        raise LegacyImportError("Не задана дата среза начальных остатков opening_date.")
    department_mapping = _normalised_mapping(mapping.get("departments"))
    item_identities = _item_identities(rows)
    source_identities = _source_identities(rows)
    for row in rows["stelazh"]:
        if WarehouseImportRecord.objects.filter(run=run, source_table="stelazh", row_hash=row["row_hash"]).exists():
            continue
        dto = opening_stock_dto(row["payload"])
        department = _resolve_department(department_mapping.get(dto["department"].casefold()))
        warehouse, _ = Warehouse.objects.get_or_create(
            department=department,
            code=f"legacy-import-{department.pk}",
            defaults={"name": "Импортированный склад"},
        )
        location, _ = StorageLocation.objects.get_or_create(
            warehouse=warehouse,
            code="unassigned",
            defaults={
                "name": "Не назначено",
                "location_type": StorageLocation.LocationType.OTHER,
                "purpose": StorageLocation.Purpose.UNASSIGNED,
            },
        )
        item_code, item_status = _resolve_opening_item(dto, item_identities)
        source_code, source_status = _resolve_opening_source(dto, source_identities)
        if item_status != "resolved" or not item_code:
            raise LegacyImportError(
                "Не удалось однозначно сопоставить позицию начального остатка."
            )
        if source_status != "resolved" or not source_code:
            raise LegacyImportError(
                "Не удалось однозначно сопоставить источник начального остатка."
            )
        item = WarehouseItem.objects.get(code=item_code)
        funding_source = FundingSource.objects.get(code=source_code)
        series, series_key = normalize_series(dto["series"])
        incomplete_reason = "Импортированная серия без полного номера или срока годности."
        source_id = f"legacy:{run.run_id}:stelazh:{row['row_hash']}"
        key = uuid.uuid5(uuid.NAMESPACE_URL, source_id)
        document, created = StockDocument.objects.get_or_create(
            idempotency_key=key,
            defaults={
                "department": department,
                "document_type": StockDocument.DocumentType.OPENING,
                "operation_date": opening_date,
                "comment": "Начальный остаток из legacy Access; физический адрес не подтверждён.",
                "created_by": actor,
                "external_source_id": source_id,
            },
        )
        if created:
            StockDocumentLine.objects.create(
                document=document,
                sequence=1,
                item=item,
                series=series,
                series_key=series_key,
                expires_on=dto["expires_on"],
                incomplete_reason=(
                    incomplete_reason if (not series or not dto["expires_on"]) else ""
                ),
                funding_source=funding_source,
                quantity=dto["quantity"],
                destination_location=location,
            )
        if document.status != StockDocument.Status.POSTED:
            post_document(
                document_id=document.pk,
                actor=actor,
                allow_legacy_unassigned=True,
            )
        _record(run, "stelazh", row, document, "created" if created else "reused")


def _opening_date(mapping: dict) -> date | None:
    value = str((mapping or {}).get("opening_date") or "").strip()
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _resolve_department(target: object) -> Department:
    text = str(target or "").strip()
    if not text:
        raise LegacyImportError("Не задано целевое подразделение для начального остатка.")
    if text.isdigit():
        department = Department.objects.filter(pk=int(text)).first()
    else:
        department = Department.objects.filter(oid=text).first()
        if department is None:
            matches = Department.objects.filter(name=text).order_by("id")[:2]
            department = matches[0] if len(matches) == 1 else None
    if department is None:
        raise LegacyImportError("Подтверждённое подразделение не найдено или неоднозначно.")
    return department


def reconcile_landing(*, run_id: str, strict: bool = False, requested_dir: Path | None = None) -> dict:
    _, manifest, rows = load_landing_package(run_id, requested_dir=requested_dir)
    run = ensure_import_run(manifest=manifest)
    include_unused_catalog = bool((run.manifest or {}).get("include_unused_catalog"))
    expected = {table: len(values) for table, values in rows.items()}
    expected["s_ls"] = len(
        _catalog_rows(rows=rows, include_unused_catalog=include_unused_catalog)
    )
    actual = {table: run.records.filter(source_table=table).count() for table in expected}
    mismatches = [table for table, count in actual.items() if table in {"istoch", "s_ls"} and count != expected[table]]
    critical = run.issues.filter(severity=WarehouseImportIssue.Severity.CRITICAL, resolved_at__isnull=True).count()
    balance_mismatches = _balance_mismatches_for_table(
        table_name="stelazh",
        rows=rows, mapping=(run.manifest or {}).get("mapping") or {}
    )
    sklad_mismatches = _balance_mismatches_for_table(
        table_name="Sklad",
        rows=rows,
        mapping=(run.manifest or {}).get("mapping") or {},
    )
    result = {
        "ok": not mismatches and not balance_mismatches and not sklad_mismatches and not (strict and critical),
        "run_id": str(run.run_id),
        "expected": expected,
        "actual_records": actual,
        "mismatches": mismatches,
        "balance_mismatches": balance_mismatches,
        "sklad_mismatches": sklad_mismatches,
        "open_critical_issues": critical,
    }
    if result["ok"]:
        run.status = WarehouseImportRun.Status.RECONCILED
        run.save(update_fields=["status"])
    return result


def _balance_mismatches_for_table(*, table_name: str, rows: dict[str, list[dict]], mapping: dict) -> list[dict]:
    """Сверить legacy-итоги выбранной таблицы с текущей проекцией."""
    if not rows.get(table_name):
        return []
    department_mapping = _normalised_mapping(mapping.get("departments"))
    item_identities = _item_identities(rows)
    source_identities = _source_identities(rows)
    expected = {}
    for row in rows[table_name]:
        dto = opening_stock_dto(row["payload"])
        if dto["quantity"] is None:
            continue
        try:
            department = _resolve_department(
                department_mapping.get(dto["department"].casefold())
            )
        except LegacyImportError:
            return [{"kind": "department_mapping_unavailable", "source_table": table_name}]
        item_code, item_status = _resolve_opening_item(dto, item_identities)
        source_code, source_status = _resolve_opening_source(dto, source_identities)
        if item_status != "resolved" or source_status != "resolved":
            return [
                {
                    "kind": "catalog_identity_unavailable",
                    "source_table": table_name,
                    "legacy_key": dto["legacy_key"],
                    "item_status": item_status,
                    "funding_source_status": source_status,
                }
            ]
        key = (
            department.pk,
            item_code,
            source_code,
        )
        expected[key] = expected.get(key, 0) + dto["quantity"]
    actual = {}
    for row in (
        StockBalance.objects.filter(department_id__in={key[0] for key in expected})
        .values("department_id", "item__code", "funding_source__code")
        .annotate(quantity=Sum("quantity"))
    ):
        key = (row["department_id"], row["item__code"], row["funding_source__code"])
        actual[key] = row["quantity"]
    mismatches = []
    for key in sorted(expected):
        if actual.get(key) != expected[key]:
            mismatches.append(
                {
                    "source_table": table_name,
                    "department_id": key[0],
                    "item_code": key[1],
                    "funding_source_code": key[2],
                    "expected": str(expected[key]),
                    "actual": str(actual.get(key, 0)),
                }
            )
    return mismatches
