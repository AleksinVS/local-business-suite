import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.postgresql_migration import default_export_dir, validate_export_package, validate_manifest


class Command(BaseCommand):
    help = "Validate imported PostgreSQL data against a migration package manifest."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            type=Path,
            default=default_export_dir(),
            help="Input directory containing manifest.json.",
        )
        parser.add_argument("--strict", action="store_true")
        parser.add_argument(
            "--package-only",
            action="store_true",
            help="Validate manifest files and row counts without comparing against the target database.",
        )

    def handle(self, *args, **options):
        if options["package_only"]:
            result = validate_export_package(options["input"])
        else:
            result = validate_manifest(options["input"], strict=options["strict"])
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("ok"):
            raise CommandError("Migration validation failed.")
