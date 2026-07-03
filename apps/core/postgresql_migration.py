import json
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db import models
from django.utils.dateparse import parse_date, parse_datetime, parse_duration, parse_time


SKIPPED_SQLITE_TABLES = {"sqlite_sequence"}
SKIPPED_MIGRATION_TABLES = {
    "auth_group_permissions",
    "auth_permission",
    "django_admin_log",
    "django_content_type",
    "django_migrations",
    "django_session",
}
PREFERRED_SQLITE_SOURCE_PREFIXES = {
    "ai_": "chat",
    "analytics_": "analytics_control",
    "memory_": "knowledge_meta",
}


@dataclass(frozen=True)
class SourceTable:
    source_alias: str
    source_path: Path
    table: str
    columns: list[str]
    row_count: int


def default_export_dir() -> Path:
    return settings.BASE_DIR / ".local" / "postgresql-migration" / "export-package"


def legacy_sqlite_databases() -> dict[str, Path]:
    return {
        alias: Path(path)
        for alias, path in getattr(settings, "LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES", {}).items()
    }


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=settings.BASE_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def sqlite_connection(path: Path) -> sqlite3.Connection:
    connection_ = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection_.row_factory = sqlite3.Row
    return connection_


def current_schema_tables() -> dict[str, list[str]]:
    from django.apps import apps

    schema = {}
    for model in apps.get_models(include_auto_created=True):
        table = model._meta.db_table
        if table in SKIPPED_MIGRATION_TABLES:
            continue
        schema[table] = [field.column for field in model._meta.local_concrete_fields]
    return schema


def current_schema_field_map() -> dict[str, dict[str, models.Field]]:
    from django.apps import apps

    schema = {}
    for model in apps.get_models(include_auto_created=True):
        table = model._meta.db_table
        if table in SKIPPED_MIGRATION_TABLES:
            continue
        schema[table] = {
            field.column: field
            for field in model._meta.local_concrete_fields
        }
    return schema


def sqlite_tables(path: Path, source_alias: str, *, target_schema: dict[str, list[str]]) -> list[SourceTable]:
    if not path.exists():
        return []

    tables = []
    with sqlite_connection(path) as source:
        rows = source.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
        for row in rows:
            table = row["name"]
            if table in SKIPPED_SQLITE_TABLES or table not in target_schema:
                continue
            source_columns = [
                column["name"]
                for column in source.execute(f"PRAGMA table_info({quote_sqlite_identifier(table)})")
            ]
            columns = [column for column in target_schema[table] if column in source_columns]
            if not columns:
                continue
            count = source.execute(f"SELECT COUNT(*) AS count FROM {quote_sqlite_identifier(table)}").fetchone()["count"]
            tables.append(
                SourceTable(
                    source_alias=source_alias,
                    source_path=path,
                    table=table,
                    columns=columns,
                    row_count=count,
                )
            )
    return tables


def quote_sqlite_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def collect_source_tables() -> list[SourceTable]:
    candidates: dict[str, list[SourceTable]] = {}
    target_schema = current_schema_tables()
    for alias, path in legacy_sqlite_databases().items():
        for table in sqlite_tables(path, alias, target_schema=target_schema):
            candidates.setdefault(table.table, []).append(table)
    return [select_source_table(table_name, tables) for table_name, tables in candidates.items()]


def select_source_table(table_name: str, candidates: list[SourceTable]) -> SourceTable:
    preferred_alias = preferred_sqlite_source_alias(table_name)
    if preferred_alias:
        for table in candidates:
            if table.source_alias == preferred_alias:
                return table
    return candidates[0]


def preferred_sqlite_source_alias(table_name: str) -> str:
    for prefix, alias in PREFERRED_SQLITE_SOURCE_PREFIXES.items():
        if table_name.startswith(prefix):
            return alias
    return ""


def write_export_package(output_dir: Path, *, dry_run: bool = False) -> dict:
    output_dir = Path(output_dir)
    source_tables = collect_source_tables()
    manifest = {
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "sources": {
            alias: str(path)
            for alias, path in legacy_sqlite_databases().items()
        },
        "tables": [
            {
                "source_alias": table.source_alias,
                "source_path": str(table.source_path),
                "table": table.table,
                "columns": table.columns,
                "row_count": table.row_count,
                "file": f"tables/{table.table}.jsonl",
            }
            for table in source_tables
        ],
    }

    if dry_run:
        return manifest

    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "manifest.json").open("w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, ensure_ascii=False, indent=2, cls=DjangoJSONEncoder)
        manifest_file.write("\n")

    for table in source_tables:
        export_table(table, tables_dir / f"{table.table}.jsonl")

    return manifest


def export_table(table: SourceTable, output_file: Path) -> None:
    with sqlite_connection(table.source_path) as source, output_file.open("w", encoding="utf-8") as target:
        rows = source.execute(f"SELECT * FROM {quote_sqlite_identifier(table.table)}")
        for row in rows:
            payload = {column: row[column] for column in table.columns}
            target.write(json.dumps(payload, ensure_ascii=False, cls=DjangoJSONEncoder))
            target.write("\n")


def load_manifest(input_dir: Path) -> dict:
    manifest_path = Path(input_dir) / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as manifest_file:
        return json.load(manifest_file)


def target_table_names() -> set[str]:
    return set(connection.introspection.table_names())


def import_manifest(input_dir: Path, *, dry_run: bool = False, replace: bool = False, batch_size: int = 500) -> dict:
    input_dir = Path(input_dir)
    manifest = load_manifest(input_dir)
    available_tables = target_table_names()
    missing_tables = [table["table"] for table in manifest["tables"] if table["table"] not in available_tables]
    if missing_tables:
        return {
            "ok": False,
            "missing_tables": missing_tables,
            "imported": {},
        }

    existing = {}
    with connection.cursor() as cursor:
        for table in manifest["tables"]:
            table_name = table["table"]
            cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table_name)}")
            count = cursor.fetchone()[0]
            if count:
                existing[table_name] = count

    if existing and not replace:
        return {
            "ok": False,
            "existing_rows": existing,
            "hint": "Run with --replace after backing up the target database.",
            "imported": {},
        }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "tables": {table["table"]: table["row_count"] for table in manifest["tables"]},
            "existing_rows": existing,
        }

    imported = {}
    with transaction.atomic():
        with connection.constraint_checks_disabled():
            if replace:
                clear_tables([table["table"] for table in manifest["tables"]])
            for table in manifest["tables"]:
                imported[table["table"]] = import_table(input_dir, table, batch_size=batch_size)
        connection.check_constraints()
        reset_sequences()

    return {
        "ok": True,
        "imported": imported,
    }


def clear_tables(table_names: list[str]) -> None:
    if not table_names:
        return
    quoted = [connection.ops.quote_name(table) for table in table_names]
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute(f"TRUNCATE {', '.join(quoted)} RESTART IDENTITY CASCADE")
        else:
            for table in reversed(quoted):
                cursor.execute(f"DELETE FROM {table}")


def import_table(input_dir: Path, table: dict, *, batch_size: int) -> int:
    table_name = table["table"]
    schema_fields = current_schema_field_map()[table_name]
    source_columns = set(table["columns"])
    columns = list(table["columns"])
    columns.extend(
        column
        for column, field in schema_fields.items()
        if column not in source_columns and should_import_missing_default_field(field)
    )
    converters = [value_converter_for_field(schema_fields[column]) for column in columns]
    quoted_table = connection.ops.quote_name(table_name)
    quoted_columns = ", ".join(connection.ops.quote_name(column) for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"

    imported = 0
    batch = []
    with (input_dir / table["file"]).open("r", encoding="utf-8") as rows_file:
        for line in rows_file:
            payload = json.loads(line)
            batch.append([
                converter(payload.get(column) if column in source_columns else None)
                for column, converter in zip(columns, converters)
            ])
            if len(batch) >= batch_size:
                imported += insert_batch(sql, batch)
                batch = []
        if batch:
            imported += insert_batch(sql, batch)
    return imported


def insert_batch(sql: str, batch: list[list]) -> int:
    with connection.cursor() as cursor:
        cursor.executemany(sql, batch)
    return len(batch)


def should_import_missing_default_field(field: models.Field) -> bool:
    if field.primary_key:
        return False
    return not field.null and field.has_default()


def value_converter_for_field(field: models.Field):
    if isinstance(field, models.BooleanField):
        converter = to_bool
    elif isinstance(field, models.JSONField):
        converter = to_json
    elif isinstance(field, models.DateTimeField):
        converter = to_datetime
    elif isinstance(field, models.DateField):
        converter = to_date
    elif isinstance(field, models.TimeField):
        converter = to_time
    elif isinstance(field, models.DurationField):
        converter = to_duration
    elif isinstance(field, models.DecimalField):
        converter = to_decimal
    else:
        converter = lambda value: value

    def convert(value):
        needs_default = value is None
        if (
            not needs_default
            and isinstance(field, models.JSONField)
            and isinstance(value, str)
            and value.strip().lower() == "null"
        ):
            needs_default = True
        if needs_default and not field.null and field.has_default():
            value = field.get_default()
        return converter(value)

    return convert


def to_bool(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    return bool(value)


def to_json(value):
    if value is None:
        return None
    if value == "":
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            pass
    return connection.ops.adapt_json_value(value, DjangoJSONEncoder)


def to_datetime(value):
    if value in {None, ""} or isinstance(value, datetime):
        return value
    return parse_datetime(str(value)) or value


def to_date(value):
    if value in {None, ""}:
        return value
    return parse_date(str(value)) or value


def to_time(value):
    if value in {None, ""}:
        return value
    return parse_time(str(value)) or value


def to_duration(value):
    if value in {None, ""}:
        return value
    return parse_duration(str(value)) or value


def to_decimal(value):
    if value in {None, ""} or isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def reset_sequences() -> None:
    from django.apps import apps
    from django.core.management.color import no_style

    sql_statements = connection.ops.sequence_reset_sql(no_style(), apps.get_models())
    if not sql_statements:
        return
    with connection.cursor() as cursor:
        for statement in sql_statements:
            cursor.execute(statement)


def validate_manifest(input_dir: Path, *, strict: bool = False) -> dict:
    manifest = load_manifest(input_dir)
    available_tables = target_table_names()
    table_results = []
    ok = True
    with connection.cursor() as cursor:
        for table in manifest["tables"]:
            table_name = table["table"]
            expected = table["row_count"]
            if table_name not in available_tables:
                ok = False
                table_results.append(
                    {
                        "table": table_name,
                        "expected": expected,
                        "actual": None,
                        "ok": False,
                        "error": "missing target table",
                    }
                )
                continue
            cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table_name)}")
            actual = cursor.fetchone()[0]
            matches = actual == expected
            ok = ok and matches
            table_results.append(
                {
                    "table": table_name,
                    "expected": expected,
                    "actual": actual,
                    "ok": matches,
                }
            )

    constraint_error = ""
    if strict:
        try:
            connection.check_constraints()
        except Exception as exc:  # noqa: BLE001 - command returns validation failure payload
            ok = False
            constraint_error = str(exc)

    return {
        "ok": ok,
        "tables": table_results,
        "constraint_error": constraint_error,
    }


def validate_export_package(input_dir: Path) -> dict:
    input_dir = Path(input_dir)
    manifest = load_manifest(input_dir)
    table_results = []
    ok = True
    for table in manifest["tables"]:
        table_name = table["table"]
        expected = int(table["row_count"])
        rows_path = input_dir / table["file"]
        if not rows_path.exists():
            ok = False
            table_results.append(
                {
                    "table": table_name,
                    "expected": expected,
                    "actual": None,
                    "ok": False,
                    "error": "missing export file",
                }
            )
            continue
        actual = 0
        with rows_path.open("r", encoding="utf-8") as rows_file:
            for line in rows_file:
                if line.strip():
                    actual += 1
        matches = actual == expected
        ok = ok and matches
        table_results.append(
            {
                "table": table_name,
                "expected": expected,
                "actual": actual,
                "ok": matches,
                "file": table["file"],
            }
        )
    return {
        "ok": ok,
        "package_only": True,
        "tables": table_results,
    }
