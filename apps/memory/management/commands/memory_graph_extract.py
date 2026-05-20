from django.core.management.base import BaseCommand, CommandError

from apps.memory.document_ingestion import extract_graph_instances
from apps.memory.models import MemorySource


class Command(BaseCommand):
    help = "Extract graph entities/facts from ready memory chunks using the accepted graph schema baseline."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", required=True, help="MemorySource code to process.")
        parser.add_argument("--dry-run", action="store_true", help="Count extractable graph items without writing them.")
        parser.add_argument("--limit", type=int, default=None, help="Optional maximum chunks to process.")

    def handle(self, *args, **options):
        try:
            source = MemorySource.objects.get(code=options["source_code"])
        except MemorySource.DoesNotExist as exc:
            raise CommandError(f"MemorySource '{options['source_code']}' does not exist. Run memory_sync_source first.") from exc
        metrics = extract_graph_instances(source=source, dry_run=options["dry_run"], limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(
                "Memory graph extraction "
                f"{'dry-run ' if options['dry_run'] else ''}finished for {source.code}: "
                f"chunks={metrics['chunks']}, entities={metrics['entities']}, "
                f"facts={metrics['facts']}, review_items={metrics['review_items']}"
            )
        )
