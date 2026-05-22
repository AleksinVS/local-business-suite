from django.core.management.base import BaseCommand

from apps.memory.chat_memory import index_knowledge_item
from apps.memory.models import MemoryKnowledgeItem


class Command(BaseCommand):
    help = "Reindex file-backed knowledge items with indexing_pending or failed status."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Count pending items without indexing.")
        parser.add_argument("--limit", type=int, default=100, help="Maximum knowledge items to index.")

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"]))
        queryset = MemoryKnowledgeItem.objects.filter(
            status=MemoryKnowledgeItem.Status.ACTIVE,
            index_status__in=["indexing_pending", "failed"],
        ).order_by("updated_at", "id")[:limit]
        items = list(queryset)
        if options["dry_run"]:
            self.stdout.write(f"Knowledge index dry-run: pending_items={len(items)}, limit={limit}")
            return

        indexed = 0
        for item in items:
            index_knowledge_item(item)
            indexed += 1
        self.stdout.write(self.style.SUCCESS(f"Indexed {indexed} knowledge item(s)."))
