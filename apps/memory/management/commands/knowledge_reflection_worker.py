from django.core.management.base import BaseCommand

from apps.memory.chat_memory import propose_reflection_candidates
from apps.memory.knowledge_files import rebuild_all_knowledge_indexes, rebuild_all_knowledge_logs
from apps.memory.models import MemoryKnowledgeItem


class Command(BaseCommand):
    help = "Run off-peak knowledge reflection: index.md/log.md regeneration and organization candidates."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show planned reflection work without writing.")
        parser.add_argument("--limit", type=int, default=100, help="Maximum personal knowledge items to scan.")

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"]))
        dry_run = bool(options["dry_run"])
        personal_count = MemoryKnowledgeItem.objects.filter(
            scope=MemoryKnowledgeItem.Scope.PERSONAL,
            status=MemoryKnowledgeItem.Status.ACTIVE,
        ).count()
        org_count = MemoryKnowledgeItem.objects.filter(
            scope=MemoryKnowledgeItem.Scope.ORGANIZATION,
            status=MemoryKnowledgeItem.Status.ACTIVE,
        ).count()
        if dry_run:
            self.stdout.write(
                "Knowledge reflection dry-run: "
                f"personal_items={personal_count}, organization_items={org_count}, scan_limit={limit}"
            )
            return

        candidates = propose_reflection_candidates(limit=limit)
        indexes_written = rebuild_all_knowledge_indexes()
        logs_written = rebuild_all_knowledge_logs()

        self.stdout.write(
            self.style.SUCCESS(
                f"Knowledge reflection created {len(candidates)} candidate(s), "
                f"regenerated {len(indexes_written)} index.md file(s), "
                f"regenerated {len(logs_written)} log.md file(s)."
            )
        )
