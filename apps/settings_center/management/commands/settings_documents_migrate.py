"""Plan/apply migration of audited legacy JSON overrides."""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.settings_center.document_migration import (
    BLOCKED_CLASSES,
    apply_migration,
    plan_migration,
    _assert_safe_output,
    _atomic_write,
)
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Спланировать или атомарно импортировать подтверждённые legacy overrides."

    def add_arguments(self, parser):
        modes = parser.add_mutually_exclusive_group()
        modes.add_argument(
            "--plan",
            action="store_true",
            help="Только план (режим по умолчанию; не меняет БД и файлы).",
        )
        modes.add_argument(
            "--apply",
            action="store_true",
            help="Применить явно выбранный dependency-closed slice в PostgreSQL.",
        )
        parser.add_argument(
            "--document-id",
            dest="document_ids",
            action="append",
            default=[],
            help="ID документа; параметр можно повторять.",
        )
        parser.add_argument("--actor-id", type=int)
        parser.add_argument("--backup-root")
        parser.add_argument("--output")
        parser.add_argument("--format", choices=("json", "table"), default="json")

    def handle(self, *args, **options):
        applying = bool(options.get("apply"))
        document_ids = options.get("document_ids") or []
        output_path = None
        if applying and not document_ids:
            raise CommandError("--apply требует хотя бы один повторяемый --document-id.")
        if applying and not options.get("actor_id"):
            raise CommandError("--apply требует --actor-id активного superuser.")
        if applying and not options.get("backup_root"):
            raise CommandError("--apply требует существующий --backup-root.")
        if options.get("output"):
            try:
                # Validate the report destination before apply creates backup
                # evidence or changes the database.
                output_path = _assert_safe_output(
                    Path(options["output"]), local_only=True
                )
            except Exception as exc:
                raise CommandError(str(exc)) from exc

        try:
            if applying:
                actor = get_user_model().objects.get(pk=options["actor_id"])
                entries = apply_migration(
                    document_ids,
                    actor=actor,
                    backup_root=options["backup_root"],
                )
                mode = "apply"
            else:
                entries = plan_migration(document_ids or None)
                mode = "plan"
        except Exception as exc:  # management command converts domain errors to CLI errors
            raise CommandError(str(exc)) from exc

        result = {
            "format": "settings-document-migration-plan-v1",
            "mode": mode,
            "documents": [entry.as_dict() for entry in entries],
            "blocked": [
                entry.document_id
                for entry in entries
                if entry.classification in BLOCKED_CLASSES
            ],
        }
        rendered = (
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
            if options["format"] == "json"
            else self._table(entries, mode)
        )
        if output_path is not None:
            try:
                _atomic_write(output_path, rendered + "\n")
            except Exception as exc:
                raise CommandError(str(exc)) from exc
        else:
            self.stdout.write(rendered)

    @staticmethod
    def _table(entries, mode):
        lines = [f"mode={mode}", "document_id\tclassification\tdefault_hash\truntime_hash\treason"]
        lines.extend(
            "\t".join(
                (
                    entry.document_id,
                    entry.classification,
                    entry.default_hash or "-",
                    entry.runtime_hash or "-",
                    entry.reason,
                )
            )
            for entry in entries
        )
        return "\n".join(lines)
