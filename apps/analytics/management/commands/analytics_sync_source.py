from django.core.management.base import BaseCommand

from apps.analytics.services import sync_analytics_source, sync_sources_from_contracts


class Command(BaseCommand):
    help = "Sync an analytics source from its declared connector contract."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", help="Analytics source code to sync.")
        parser.add_argument("--dry-run", action="store_true", help="Validate source sync without writing runtime objects.")

    def handle(self, *args, **options):
        if not options.get("source_code"):
            sources = sync_sources_from_contracts()
            self.stdout.write(f"Analytics sources synced from contracts: {len(sources)}")
            return
        result = sync_analytics_source(source_code=options["source_code"], dry_run=options["dry_run"])
        self.stdout.write(
            "Analytics source sync "
            f"source={result.source_code} discovered={result.discovered} "
            f"created={result.created} updated={result.updated} dry_run={result.dry_run}"
        )
