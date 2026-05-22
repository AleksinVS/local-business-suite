from django.core.management.base import BaseCommand, CommandError

from apps.memory.document_ingestion import ingest_source_objects
from apps.memory.models import MemorySource


class Command(BaseCommand):
    help = "Ingest discovered local/UNC corporate documents into safe memory corpus and indexes."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", required=True, help="MemorySource code to ingest.")
        parser.add_argument("--dry-run", action="store_true", help="Show ingestion metrics without writing search documents.")
        parser.add_argument("--limit", type=int, default=None, help="Optional maximum source objects to process.")

    def handle(self, *args, **options):
        source_code = options["source_code"]
        try:
            source = MemorySource.objects.get(code=source_code)
        except MemorySource.DoesNotExist as exc:
            raise CommandError(f"MemorySource '{source_code}' does not exist. Run memory_sync_source first.") from exc

        metrics = ingest_source_objects(source=source, dry_run=options["dry_run"], limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(
                "Memory ingestion "
                f"{'dry-run ' if options['dry_run'] else ''}finished for {source.code}: "
                f"eligible={metrics['eligible']}, ingested={metrics['ingested']}, "
                f"partial={metrics['partial']}, skipped={metrics['skipped']}, issues={metrics['issues']}"
            )
        )
