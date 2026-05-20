from django.core.management.base import BaseCommand, CommandError

from apps.memory.document_ingestion import discover_source_objects
from apps.memory.models import MemorySource


class Command(BaseCommand):
    help = "Discover local/UNC corporate document source objects for AI memory ingestion."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", required=True, help="MemorySource code to discover.")
        parser.add_argument("--dry-run", action="store_true", help="Show discovery metrics without writing state.")

    def handle(self, *args, **options):
        source_code = options["source_code"]
        try:
            source = MemorySource.objects.get(code=source_code)
        except MemorySource.DoesNotExist as exc:
            raise CommandError(f"MemorySource '{source_code}' does not exist. Run memory_sync_source first.") from exc

        metrics = discover_source_objects(source=source, dry_run=options["dry_run"])
        self.stdout.write(
            self.style.SUCCESS(
                "Memory discovery "
                f"{'dry-run ' if options['dry_run'] else ''}finished for {source.code}: "
                f"seen={metrics['seen']}, new={metrics['new']}, changed={metrics['changed']}, "
                f"unchanged={metrics['unchanged']}, missing={metrics['missing']}, issues={metrics['issues']}"
            )
        )
