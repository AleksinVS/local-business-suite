import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.warehouse.legacy_import.landing import LandingPackageError, package_dir
from apps.warehouse.legacy_import.services import LegacyImportError, reconcile_landing


class Command(BaseCommand):
    help = "Сверить landing package legacy-склада с результатом доменного импорта."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--landing-dir", type=Path)
        parser.add_argument("--strict", action="store_true")

    def handle(self, *args, **options):
        try:
            target = package_dir(options["run_id"], requested=options["landing_dir"]) if options["landing_dir"] else package_dir(options["run_id"])
            result = reconcile_landing(run_id=options["run_id"], strict=options["strict"], requested_dir=target)
        except (LandingPackageError, LegacyImportError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if not result.get("ok"):
            raise CommandError("Строгая сверка legacy-импорта не пройдена.")
