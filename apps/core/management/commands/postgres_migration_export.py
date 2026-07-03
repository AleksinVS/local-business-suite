import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.core.postgresql_migration import default_export_dir, write_export_package


class Command(BaseCommand):
    help = "Export legacy SQLite runtime data into a PostgreSQL migration package."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=Path,
            default=default_export_dir(),
            help="Output directory for manifest.json and table JSONL files.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        manifest = write_export_package(options["output"], dry_run=options["dry_run"])
        self.stdout.write(json.dumps(manifest, ensure_ascii=False, indent=2))
