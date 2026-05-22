from django.core.management.base import BaseCommand

from apps.memory.chat_memory import process_queued_memory_requests
from apps.memory.models import MemoryWriteRequest


class Command(BaseCommand):
    help = "Process queued memory.remember write requests through the knowledge writer path."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show queued request count without writing.")
        parser.add_argument("--limit", type=int, default=100, help="Maximum queued requests to process.")

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"]))
        queued_count = MemoryWriteRequest.objects.filter(status=MemoryWriteRequest.Status.QUEUED).count()
        if options["dry_run"]:
            self.stdout.write(f"Knowledge writer dry-run: queued_requests={queued_count}, limit={limit}")
            return

        processed = process_queued_memory_requests(limit=limit)
        self.stdout.write(self.style.SUCCESS(f"Knowledge writer processed {len(processed)} request(s)."))
