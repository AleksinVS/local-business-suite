from django.core.management.base import BaseCommand

from apps.analytics.services import recalculate_metrics


class Command(BaseCommand):
    help = "Recalculate analytics metrics and evaluate monitors."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Calculate without writing snapshots/signals.")

    def handle(self, *args, **options):
        result = recalculate_metrics(dry_run=options["dry_run"])
        self.stdout.write(
            "Analytics metrics recalculated "
            f"snapshots={result['snapshots']} signals={result['signals']} dry_run={result['dry_run']}"
        )
