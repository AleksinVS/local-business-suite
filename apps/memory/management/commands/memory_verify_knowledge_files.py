from django.core.management.base import BaseCommand, CommandError

from apps.memory.knowledge_files import verify_knowledge_item_file
from apps.memory.models import MemoryKnowledgeItem


class Command(BaseCommand):
    help = "Verify MemoryKnowledgeItem metadata against file-backed knowledge files."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Return an error if any mismatch is found.")

    def handle(self, *args, **options):
        checked = 0
        failed = []
        for item in MemoryKnowledgeItem.objects.order_by("id"):
            result = verify_knowledge_item_file(item)
            checked += 1
            if not result["ok"]:
                failed.append(result)

        self.stdout.write(f"Knowledge file verification: checked={checked}, failed={len(failed)}")
        for result in failed[:20]:
            self.stdout.write(
                f"- {result['memory_id']}: file_exists={result['file_exists']} "
                f"text_hash={result['text_hash']} metadata_text_hash={result['metadata_text_hash']}"
            )
        if failed and options["strict"]:
            raise CommandError("Knowledge file verification failed.")
