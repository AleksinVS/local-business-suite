"""Полная очистка данных листа ожидания."""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.waiting_list.data_operations import clear_waiting_list_data
from apps.waiting_list.models import WaitingListAuditLog, WaitingListEntry


CONFIRMATION = "DELETE_WAITING_LIST"


class Command(BaseCommand):
    help = "Удалить все записи и журнал изменений листа ожидания."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать объём удаления без изменения базы.",
        )
        parser.add_argument(
            "--confirm",
            default="",
            help=f"Для удаления передайте точное значение {CONFIRMATION}.",
        )
        parser.add_argument(
            "--skip-projections",
            action="store_true",
            help="Не очищать производные поисковые и аналитические проекции.",
        )

    def handle(self, *args, **options):
        entries = WaitingListEntry.objects.count()
        audit_rows = WaitingListAuditLog.objects.count()
        self.stdout.write(
            f"Найдено: записей={entries}, событий журнала={audit_rows}."
        )
        if options["dry_run"]:
            self.stdout.write("Предварительный просмотр завершён; база не изменена.")
            return
        if options["confirm"] != CONFIRMATION:
            raise CommandError(
                f"Удаление не выполнено. Передайте --confirm {CONFIRMATION}."
            )

        entries, audit_rows = clear_waiting_list_data()
        self.stdout.write(
            self.style.SUCCESS(
                f"Удалено: записей={entries}, событий журнала={audit_rows}."
            )
        )

        if not options["skip_projections"]:
            call_command(
                "source_adapter_reconcile",
                source_code="waiting_list",
                target="all",
                backend="all",
                stdout=self.stdout,
                stderr=self.stderr,
            )
