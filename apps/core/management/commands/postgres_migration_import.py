import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.postgresql_migration import default_export_dir, import_manifest


class Command(BaseCommand):
    help = "Import a PostgreSQL migration package into the default database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            type=Path,
            default=default_export_dir(),
            help="Input directory containing manifest.json and table JSONL files.",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete target rows for manifest tables before import. Requires a backup.",
        )
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        result = import_manifest(
            options["input"],
            dry_run=options["dry_run"],
            replace=options["replace"],
            batch_size=options["batch_size"],
        )
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("ok"):
            raise CommandError("Import preflight failed.")
