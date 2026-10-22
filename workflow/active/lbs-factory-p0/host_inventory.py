"""P0 host inventory: aggregate metadata only; no migration or business writes.

Run with the deployment's Python and environment. A separately launched process
does not prove that IIS workers use the same environment. Copy this artifact to
the host's .local directory; never put its result or deployment secrets in Git.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone
from tempfile import NamedTemporaryFile


TABLES = (
    "core_department", "accounts_user", "auth_group", "accounts_groupprofile",
    "accounts_user_groups", "accounts_user_user_permissions", "auth_permission",
    "auth_group_permissions", "django_content_type", "accounts_externalidentity",
    "accounts_accessassignmentaudit", "waiting_list_waitinglistentry",
    "waiting_list_waitinglistauditlog", "inventory_medicaldevice",
    "settings_center_runtimesettingdocument", "settings_center_settingschange",
    "settings_center_settingschangecomment", "memory_memorysourceobject",
    "memory_memoryknowledgeitem", "memory_memorysearchdocument", "memory_memoryfulltextindex",
)
REQUIRED_TABLES = frozenset({
    "accounts_user", "auth_group", "core_department",
    "waiting_list_waitinglistentry", "waiting_list_waitinglistauditlog",
    "inventory_medicaldevice",
})
SAFE_SETTINGS = (
    "DJANGO_ENV", "DJANGO_AUTH_MODE", "LOCAL_BUSINESS_DB_BACKEND",
    "LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE",
    "LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED", "LOCAL_BUSINESS_AI_UI_DRIVER",
    "LOCAL_BUSINESS_AI_UI_AGUI_PROFILE", "ACCOUNTS_AD_LINK_MODE",
)


def digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    project = options.project_root.resolve()
    local = project / ".local"
    output = (options.output or local / "lbs-factory-p0" / "host-inventory.json").resolve()
    if not (project / "manage.py").is_file():
        parser.error("project-root must contain manage.py")
    if local.is_symlink() or not output.is_relative_to(local.resolve()):
        parser.error("output must be inside the project's non-symlink .local directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(project))
    os.chdir(project)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    report = {
        "schema_version": 1,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "observation": "standalone process; IIS worker environment not attested",
        "personal_data_exported": False,
        "business_writes_requested": False,
        "table_counts": {}, "errors": [],
        "not_verified": ["IIS effective environment", "backup and restore",
                         "source row content equivalence", "permissions equivalence"],
    }
    report["code_head"] = None
    try:
        head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=False)
        if head.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", head.stdout.strip()):
            report["code_head"] = head.stdout.strip()
    except OSError:
        # Git is optional on a Windows deployment. Keep collecting metadata;
        # the operator must establish the deployed source version separately.
        pass
    if report["code_head"] is None:
        report["not_verified"].append("deployed source revision; Git unavailable or no checkout")
    try:
        import django
        django.setup()
        from django.conf import settings
        from django.db import connection, transaction

        report["django_version"] = django.get_version()
        report["process_settings"] = {
            name: getattr(settings, name, None) for name in SAFE_SETTINGS
        }
        report["database_vendor"] = connection.vendor
        if connection.vendor not in {"sqlite", "postgresql"}:
            raise RuntimeError("unsupported_database_for_read_only_inventory")
        if connection.vendor == "sqlite":
            # SQLite may create a missing database when opening it normally.
            name = str(connection.settings_dict["NAME"])
            if not Path(name).is_file():
                raise RuntimeError("existing_sqlite_file_required")
            connection.close()
            connection.settings_dict["NAME"] = Path(name).resolve().as_uri() + "?mode=ro"
            connection.settings_dict.setdefault("OPTIONS", {})["uri"] = True
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA query_only=ON")
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            with connection.cursor() as cursor:
                tables = set(connection.introspection.table_names(cursor))
                quote = connection.ops.quote_name
                for table in TABLES:
                    if table not in tables:
                        report["table_counts"][table] = None
                        continue
                    cursor.execute("SELECT COUNT(*) FROM " + quote(table))
                    report["table_counts"][table] = cursor.fetchone()[0]
                report["missing_required_tables"] = sorted(REQUIRED_TABLES - tables)
                if "django_migrations" in tables:
                    cursor.execute("SELECT app, name FROM django_migrations ORDER BY app, name")
                    migrations = cursor.fetchall()
                    report["migration_records"] = len(migrations)
                    report["migration_state_sha256"] = digest(migrations)
            # Older deployments may not implement the new repository. Its absence
            # is reported, never treated as an empty role document.
            try:
                with transaction.atomic():
                    from apps.core.contract_store import get_contract
                    roles = get_contract("role_rules")
                    report["role_document_sha256"] = digest(roles)
                    report["role_count"] = len([k for k in roles if not k.startswith("$")])
                    from apps.settings_center.document_registry import get_document_registry
                    registry = get_document_registry()
                    report["role_document_backend"] = registry.get(
                        "core.contract.role_rules",
                    ).active_backend
                    report["database_document_ids"] = [
                        spec.document_id for spec in registry.all()
                        if spec.active_backend == "database"
                    ]
            except Exception as exc:
                report["errors"].append({"stage": "role_document", "type": type(exc).__name__})
        connection.close()
    except Exception as exc:
        # Exception text may include credentials, hostnames or source data.
        report["errors"].append({"stage": "inventory", "type": type(exc).__name__})
    temporary = None
    try:
        # An exclusive unpredictable file avoids following a pre-existing
        # <output>.tmp symlink. Replace happens in the validated directory.
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                prefix=".p0-inventory-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print("Inventory report saved; no row values or secrets printed.")
    return 1 if report["errors"] or report.get("missing_required_tables") else 0


if __name__ == "__main__":
    raise SystemExit(main())
