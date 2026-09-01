import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.warehouse.legacy_import.landing import LandingPackageError, package_dir
from apps.warehouse.legacy_import.services import LegacyImportError, extract_access_landing, import_landing, load_mapping


class Command(BaseCommand):
    help = "Подготовить и идемпотентно импортировать legacy Access landing package склада."

    def add_arguments(self, parser):
        parser.add_argument("--adapter", default="access-v1")
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--source", type=Path)
        parser.add_argument("--landing-dir", type=Path)
        parser.add_argument("--mappings", type=Path)
        parser.add_argument("--actor", help="Активный складской оператор; обязателен для --commit.")
        parser.add_argument("--include-unused-catalog", action="store_true")
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--commit", action="store_true")
        parser.add_argument("--sample-size", type=int, default=5)

    def handle(self, *args, **options):
        if options["adapter"] != "access-v1":
            raise CommandError("Поддерживается только adapter access-v1.")
        try:
            target = package_dir(options["run_id"], requested=options["landing_dir"]) if options["landing_dir"] else package_dir(options["run_id"])
            if options["source"] and not (target / "manifest.json").exists():
                extract_access_landing(run_id=options["run_id"], source=options["source"], requested_dir=target, sample_size=options["sample_size"])
            if not (target / "manifest.json").exists():
                raise LegacyImportError("Для run-id нет landing package; укажите --source для первой dry-run выгрузки.")
            actor = None
            if options["actor"]:
                actor = get_user_model().objects.filter(username__iexact=options["actor"], is_active=True).first()
                if actor is None:
                    raise LegacyImportError("Активный оператор --actor не найден.")
            result = import_landing(
                run_id=options["run_id"], mapping=load_mapping(options["mappings"]),
                commit=options["commit"], actor=actor,
                include_unused_catalog=options["include_unused_catalog"], requested_dir=target,
            )
        except (LandingPackageError, LegacyImportError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        if not result.get("ok"):
            raise CommandError("Подготовка импорта обнаружила критические проблемы.")
