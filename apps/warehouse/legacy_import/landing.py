"""Безопасное хранение воспроизводимого landing package склада."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from django.conf import settings

from .access_v1 import SECRET_COLUMN_NAMES


LANDING_SCHEMA_VERSION = "warehouse-access-landing-v1"


class LandingPackageError(ValueError):
    pass


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: object):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def sha256_payload(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def validate_run_id(run_id: str | uuid.UUID) -> str:
    try:
        return str(uuid.UUID(str(run_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LandingPackageError("run-id должен быть UUID.") from exc


def import_root() -> Path:
    return Path(settings.DATA_DIR) / "warehouse" / "imports"


def local_import_root() -> Path:
    return Path(settings.BASE_DIR) / ".local" / "warehouse-import"


def package_dir(run_id: str | uuid.UUID, *, requested: Path | None = None) -> Path:
    normalized = validate_run_id(run_id)
    canonical = (import_root() / normalized).resolve()
    if requested is None:
        return canonical
    candidate = Path(requested).resolve()
    allowed_roots = (import_root().resolve(), local_import_root().resolve())
    if not any(_is_relative_to(candidate, root) for root in allowed_roots):
        raise LandingPackageError("Пакет миграции можно создавать только в data/warehouse/imports или .local/warehouse-import.")
    # A caller can choose the root, but cannot make a package escape its run-id.
    if candidate.name != normalized:
        raise LandingPackageError("Каталог пакета должен оканчиваться точным run-id.")
    return candidate


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def safe_payload(payload: dict) -> dict:
    """Удалить поля, похожие на секреты, до хеширования и сериализации."""
    result = {}
    for key, value in (payload or {}).items():
        normalized = str(key).strip().casefold()
        if normalized in SECRET_COLUMN_NAMES or any(token in normalized for token in ("password", "secret", "token")):
            continue
        result[str(key)] = value
    return result


def write_landing_package(
    *,
    run_id: str | uuid.UUID,
    source_fingerprint: str,
    source_name: str,
    adapter: str,
    transformation_version: str,
    tables: dict[str, Iterable[dict]],
    schema: dict[str, dict] | None = None,
    requested_dir: Path | None = None,
) -> tuple[Path, dict]:
    """Записать неизменяемый transport snapshot как manifest + JSONL.

    Повторная запись с другим содержимым для того же run-id отклоняется. Это
    исключает незаметную замену входных данных между dry-run и commit.
    """
    target = package_dir(run_id, requested=requested_dir)
    target.mkdir(parents=True, exist_ok=True)
    tables_dir = target / "tables"
    tables_dir.mkdir(exist_ok=True)
    table_entries = []
    for table_name in sorted(tables):
        safe_name = str(table_name).strip()
        if not safe_name or any(char in safe_name for char in "\\/:"):
            raise LandingPackageError("Недопустимое имя legacy-таблицы.")
        rows_path = tables_dir / f"{safe_name}.jsonl"
        lines = []
        hashes = set()
        for raw_row in tables[table_name]:
            payload = safe_payload(dict(raw_row or {}))
            row_hash = sha256_payload(payload)
            if row_hash in hashes:
                raise LandingPackageError(f"В таблице {safe_name} есть неразличимые дублирующие строки.")
            hashes.add(row_hash)
            lines.append(
                _canonical_json(
                    {
                        "schema_version": LANDING_SCHEMA_VERSION,
                        "source_table": safe_name,
                        "source_identity": {"kind": "row_hash", "value": row_hash},
                        "row_hash": row_hash,
                        "payload": payload,
                    }
                )
            )
        content = "\n".join(lines) + ("\n" if lines else "")
        _write_immutable_text(rows_path, content)
        schema_entry = (schema or {}).get(table_name, {})
        columns = [
            column
            for column in schema_entry.get("columns", sorted({key for raw in tables[table_name] for key in safe_payload(raw)}))
            if str(column).strip().casefold() not in SECRET_COLUMN_NAMES
        ]
        table_entries.append(
            {
                "name": safe_name,
                "columns": columns,
                "indexes": schema_entry.get("indexes", []),
                "row_count": len(lines),
                "file": f"tables/{safe_name}.jsonl",
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            }
        )
    manifest = {
        "schema_version": LANDING_SCHEMA_VERSION,
        "run_id": validate_run_id(run_id),
        "adapter": adapter,
        "transformation_version": transformation_version,
        "source_fingerprint": source_fingerprint,
        "source_name": Path(source_name).name,
        "tables": table_entries,
        "intentionally_skipped": ["sett", "tmp", "treb", "s_otdelenie.pass"],
    }
    manifest["manifest_sha256"] = sha256_payload({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    _write_immutable_text(target / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return target, manifest


def _write_immutable_text(path: Path, content: str) -> None:
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != content:
            raise LandingPackageError("Landing package уже существует и отличается от нового снимка.")
        return
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def load_landing_package(run_id: str | uuid.UUID, *, requested_dir: Path | None = None) -> tuple[Path, dict, dict[str, list[dict]]]:
    target = package_dir(run_id, requested=requested_dir)
    try:
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LandingPackageError("Не найден корректный manifest landing package.") from exc
    if manifest.get("schema_version") != LANDING_SCHEMA_VERSION or manifest.get("run_id") != validate_run_id(run_id):
        raise LandingPackageError("Manifest landing package не соответствует run-id или версии схемы.")
    expected_hash = sha256_payload({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    if manifest.get("manifest_sha256") != expected_hash:
        raise LandingPackageError("Manifest landing package повреждён.")
    loaded = {}
    for table in manifest.get("tables", []):
        path = target / table["file"]
        if not _is_relative_to(path.resolve(), target.resolve()):
            raise LandingPackageError("Manifest ссылается за пределы landing package.")
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LandingPackageError(f"Не удалось прочитать JSONL таблицы {table.get('name')}.") from exc
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != table.get("sha256"):
            raise LandingPackageError(f"JSONL таблицы {table.get('name')} повреждён.")
        try:
            rows = [json.loads(line) for line in content.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise LandingPackageError(f"JSONL таблицы {table.get('name')} повреждён.") from exc
        if len(rows) != table.get("row_count"):
            raise LandingPackageError(f"Число строк JSONL таблицы {table.get('name')} не совпадает с manifest.")
        loaded[table["name"]] = rows
    return target, manifest, loaded
