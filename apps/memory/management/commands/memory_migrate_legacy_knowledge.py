import json
import sqlite3

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.memory.chat_memory import index_knowledge_item
from apps.memory.knowledge_files import write_knowledge_item_file
from apps.memory.models import MemoryKnowledgeItem


class Command(BaseCommand):
    help = "Copy legacy MemoryKnowledgeItem rows from main_vault.sqlite3 to knowledge_meta and export files."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Count legacy rows without writing.")
        parser.add_argument("--no-index", action="store_true", help="Do not rebuild search index after export.")

    def handle(self, *args, **options):
        db_path = settings.DATABASES["default"]["NAME"]
        rows = _legacy_rows(db_path)
        if options["dry_run"]:
            self.stdout.write(f"Legacy knowledge migration dry-run: legacy_rows={len(rows)}")
            return

        migrated = 0
        for row in rows:
            if not str(row.get("text") or "").strip():
                continue
            item = _upsert_target_item(row)
            write_knowledge_item_file(item, body=row.get("text") or "", commit_message=f"Migrate legacy knowledge {item.memory_id}")
            if not options["no_index"] and item.status == MemoryKnowledgeItem.Status.ACTIVE:
                index_knowledge_item(item)
            migrated += 1
        self.stdout.write(self.style.SUCCESS(f"Migrated {migrated} legacy knowledge item(s)."))


def _legacy_rows(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'memory_memoryknowledgeitem'"
        ).fetchone()
        if table is None:
            return []
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(memory_memoryknowledgeitem)")}
        selected = [
            column
            for column in (
                "memory_id",
                "scope",
                "owner_user_id",
                "kind",
                "text",
                "text_hash",
                "sensitivity",
                "scope_tokens",
                "status",
                "source_session_id",
                "source_message_ids",
                "source_content_hash",
                "provenance",
                "metadata",
                "created_by_id",
                "created_at",
                "updated_at",
            )
            if column in columns
        ]
        if not selected:
            return []
        sql = f"SELECT {', '.join(selected)} FROM memory_memoryknowledgeitem ORDER BY id"
        return [dict(row) for row in connection.execute(sql)]
    finally:
        connection.close()


def _upsert_target_item(row):
    source_message_ids = _json_value(row.get("source_message_ids"), [])
    source_refs = []
    if row.get("source_session_id"):
        source_refs = [
            {
                "kind": "chat_message",
                "value": f"chat_session:{row.get('source_session_id')}/message:{message_id}",
            }
            for message_id in source_message_ids
        ]
    item, _created = MemoryKnowledgeItem.objects.update_or_create(
        memory_id=row["memory_id"],
        defaults={
            "scope": row.get("scope") or MemoryKnowledgeItem.Scope.PERSONAL,
            "owner_user_id": row.get("owner_user_id"),
            "kind": row.get("kind") or MemoryKnowledgeItem.Kind.FACT,
            "text_hash": row.get("text_hash") or "",
            "sensitivity": row.get("sensitivity") or "internal",
            "scope_tokens": _json_value(row.get("scope_tokens"), []),
            "status": row.get("status") or MemoryKnowledgeItem.Status.ACTIVE,
            "source_session_id": row.get("source_session_id"),
            "source_message_ids": source_message_ids,
            "source_refs": source_refs,
            "source_code": "chat",
            "source_kind": "chat",
            "source_content_hash": row.get("source_content_hash") or "",
            "provenance": _json_value(row.get("provenance"), {}),
            "metadata": {**_json_value(row.get("metadata"), {}), "legacy_main_vault": True},
            "created_by_id": row.get("created_by_id"),
            "index_status": "indexing_pending",
        },
    )
    return item


def _json_value(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default
    return parsed
