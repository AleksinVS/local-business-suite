from django.core.management.base import BaseCommand

from apps.analytics.services import dedup_analytics_source


class Command(BaseCommand):
    help = "Find duplicate and near-duplicate analytics content objects for a source."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", required=True, help="Analytics source code.")
        parser.add_argument("--dry-run", action="store_true", help="Report duplicates without writing candidates.")

    def handle(self, *args, **options):
        result = dedup_analytics_source(source_code=options["source_code"], dry_run=options["dry_run"])
        self.stdout.write(
            "Analytics dedup finished "
            f"source={result['source_code']} candidates={result['candidates']} "
            f"created={result['created']} dry_run={result['dry_run']}"
        )
