import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.integrations.ace_legacy import AccessTransportError, run_access_export
from apps.warehouse.legacy_import.access_v1 import TABLES
from apps.warehouse.legacy_import.landing import package_dir, validate_run_id


class Command(BaseCommand):
    help = "Безопасно показать schema/count/sample Access-источника склада без импорта."

    def add_arguments(self, parser):
        parser.add_argument("--adapter", default="access-v1")
        parser.add_argument("--source", type=Path, required=True)
        parser.add_argument("--run-id", default="00000000-0000-0000-0000-000000000000")
        parser.add_argument("--sample-size", type=int, default=5)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["adapter"] != "access-v1":
            raise CommandError("Поддерживается только adapter access-v1.")
        try:
            output = package_dir(validate_run_id(options["run_id"])) / "inspect"
            manifest = run_access_export(source=options["source"], output_dir=output, tables=TABLES, sample_size=options["sample_size"], inspect_only=True)
        except (AccessTransportError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
