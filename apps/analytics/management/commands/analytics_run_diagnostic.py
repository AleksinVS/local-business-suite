from django.core.management.base import BaseCommand, CommandError

from apps.analytics.models import AnalyticsSignal
from apps.analytics.services import run_signal_diagnostic


class Command(BaseCommand):
    help = "Run AI-diagnostic workflow for an analytics signal."

    def add_arguments(self, parser):
        parser.add_argument("--signal-id", required=True, help="AnalyticsSignal.signal_id.")
        parser.add_argument("--dry-run", action="store_true", help="Build diagnostic evidence without creating a case.")

    def handle(self, *args, **options):
        if not AnalyticsSignal.objects.filter(signal_id=options["signal_id"]).exists():
            raise CommandError(f"Analytics signal '{options['signal_id']}' does not exist.")
        result = run_signal_diagnostic(signal_id=options["signal_id"], dry_run=options["dry_run"])
        self.stdout.write(
            "Analytics diagnostic finished "
            f"run_id={result['diagnostic_run_id']} signal={result['signal_id']} "
            f"route={result['route']} case={result['case_id']} dry_run={result['dry_run']}"
        )
