from django.core.management.base import BaseCommand

from apps.memory.knowledge_files import read_knowledge_item_file, write_knowledge_item_file
from apps.memory.models import MemoryKnowledgeItem


class Command(BaseCommand):
    help = "Rewrite existing file-backed knowledge files and refresh their hashes."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Count rows without writing files.")
        parser.add_argument("--limit", type=int, default=0, help="Optional maximum number of rows.")

    def handle(self, *args, **options):
        queryset = MemoryKnowledgeItem.objects.filter(status=MemoryKnowledgeItem.Status.ACTIVE).order_by("created_at", "id")
        if options["limit"]:
            queryset = queryset[: max(1, int(options["limit"]))]
        items = list(queryset)
        if options["dry_run"]:
            self.stdout.write(f"Knowledge export dry-run: active_items={len(items)}")
            return

        exported = 0
        for item in items:
            body = read_knowledge_item_file(item).body
            write_knowledge_item_file(item, body=body, commit_message=f"Refresh knowledge file {item.memory_id}")
            exported += 1
        self.stdout.write(self.style.SUCCESS(f"Exported {exported} knowledge item(s)."))
