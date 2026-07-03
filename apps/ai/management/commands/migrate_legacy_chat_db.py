import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


CHAT_TABLES = (
    "ai_chatsession",
    "ai_chatmessage",
    "ai_chatattachment",
    "ai_pendingaction",
    "ai_agentactionlog",
)


class Command(BaseCommand):
    help = "Copy legacy AI chat tables from main_vault.sqlite3 to data/db/chat.sqlite3."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show source and target counts without copying.")

    def handle(self, *args, **options):
        legacy_paths = getattr(settings, "LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES", {})
        legacy_db = legacy_paths.get("default")
        target_db = legacy_paths.get("chat")
        if not legacy_db or not target_db:
            raise CommandError("Legacy SQLite paths are not configured.")
        report = copy_tables(legacy_db=legacy_db, target_db=target_db, tables=CHAT_TABLES, dry_run=options["dry_run"])
        for table, counts in report.items():
            self.stdout.write(
                f"{table}: legacy={counts['legacy']}, target_before={counts['target_before']}, copied={counts['copied']}"
            )
        if not options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Legacy chat database migration finished."))


def copy_tables(*, legacy_db, target_db, tables, dry_run):
    connection = sqlite3.connect(target_db)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("ATTACH DATABASE ? AS legacy", (str(legacy_db),))
        report = {}
        for table in tables:
            if not _table_exists(connection, "legacy", table) or not _table_exists(connection, "main", table):
                report[table] = {"legacy": 0, "target_before": 0, "copied": 0}
                continue
            legacy_count = _table_count(connection, "legacy", table)
            target_before = _table_count(connection, "main", table)
            copied = 0
            if not dry_run:
                target_columns = _columns(connection, "main", table)
                legacy_columns = _columns(connection, "legacy", table)
                columns = [column for column in target_columns if column in legacy_columns]
                column_sql = ", ".join(columns)
                before_changes = connection.total_changes
                connection.execute(
                    f"INSERT OR IGNORE INTO main.{table} ({column_sql}) "
                    f"SELECT {column_sql} FROM legacy.{table}"
                )
                copied = connection.total_changes - before_changes
            report[table] = {"legacy": legacy_count, "target_before": target_before, "copied": copied}
        if not dry_run:
            connection.commit()
        return report
    finally:
        connection.close()


def _table_exists(connection, schema, table):
    return (
        connection.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _table_count(connection, schema, table):
    return int(connection.execute(f"SELECT COUNT(*) FROM {schema}.{table}").fetchone()[0])


def _columns(connection, schema, table):
    return [row["name"] for row in connection.execute(f"PRAGMA {schema}.table_info({table})")]
