from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.settings_center.access_migration_services import report_roleless_users


class Command(BaseCommand):
    help = "Create a read-only report for active users without an explicit role."

    def add_arguments(self, parser):
        parser.add_argument("--output", help="Runtime JSON report path.")

    def handle(self, *args, **options):
        output = options.get("output")
        if output is None:
            root = Path(settings.DATA_DIR) / "access-migrations"
            output = root / "roleless-users.latest.json"
        try:
            report = report_roleless_users(output_path=output)
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Отчёт создан: users={len(report['users'])}, boards={len(report['customer_open_boards'])}, "
                f"hash={report['report_hash']}, path={output}"
            )
        )
