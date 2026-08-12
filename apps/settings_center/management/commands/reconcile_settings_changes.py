from django.core.management.base import BaseCommand, CommandError

from apps.settings_center.contract_services import reconcile_pending_contract_changes


class Command(BaseCommand):
    help = "Сверить незавершённые записи рабочих контрактов с фактическими файлами."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Зафиксировать однозначно определяемые статусы; без флага выполняется dry-run.",
        )
        parser.add_argument("--setting-id", default="", help="Ограничить сверку одной настройкой.")

    def handle(self, *args, **options):
        try:
            reports = reconcile_pending_contract_changes(
                apply=options["apply"],
                setting_id=options["setting_id"] or None,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        mode = "apply" if options["apply"] else "dry-run"
        self.stdout.write(f"Режим: {mode}; незавершённых изменений: {len(reports)}")
        for report in reports:
            self.stdout.write(
                "#{id} {setting_id}: {classification}; before={before_hash} "
                "after={after_hash} actual={actual_hash}".format(**report)
            )
