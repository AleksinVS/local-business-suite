from django.core.management.base import BaseCommand
from apps.memory.chat_memory import process_queued_memory_requests
from apps.memory.models import MemoryWriteRequest


class Command(BaseCommand):
    help = (
        "Compatibility alias: process queued memory.remember requests. "
        "Use knowledge_reflection_worker for off-peak reflection."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show planned queue processing work without writing.")
        parser.add_argument("--limit", type=int, default=100, help="Maximum queued requests/items to process.")
        parser.add_argument("--window-hours", type=int, default=24, help="Ignored compatibility option.")

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"]))
        dry_run = bool(options["dry_run"])
        queued_count = MemoryWriteRequest.objects.filter(status=MemoryWriteRequest.Status.QUEUED).count()
        if dry_run:
            self.stdout.write(
                "Memory queue processor dry-run: "
                f"queued_requests={queued_count}, limit={limit}, reflection_processed=False"
            )
            return

        processed = process_queued_memory_requests(limit=limit)

        self.stdout.write(
            self.style.SUCCESS(
                "Memory queue processor succeeded: "
                f"processed_requests={len(processed)}, reflection_processed=False"
            )
        )
