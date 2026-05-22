from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.memory.chat_memory import propose_reflection_candidates
from apps.memory.knowledge_files import rebuild_knowledge_summaries
from apps.memory.models import MemoryKnowledgeItem, MemoryReflectionRun


class Command(BaseCommand):
    help = "Run off-peak knowledge reflection: summaries and candidates, without processing write queue."

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

        run = MemoryReflectionRun.objects.create(
            status=MemoryReflectionRun.Status.RUNNING,
            dry_run=False,
            window_end=timezone.now(),
            started_at=timezone.now(),
        )
        try:
            candidates = propose_reflection_candidates(limit=limit)
            rebuild_knowledge_summaries(scope=MemoryKnowledgeItem.Scope.ORGANIZATION)
            for owner_id in (
                MemoryKnowledgeItem.objects.filter(
                    scope=MemoryKnowledgeItem.Scope.PERSONAL,
                    status=MemoryKnowledgeItem.Status.ACTIVE,
                )
                .values_list("owner_user_id", flat=True)
                .distinct()
            ):
                if owner_id:
                    item = MemoryKnowledgeItem.objects.filter(owner_user_id=owner_id).first()
                    rebuild_knowledge_summaries(scope=MemoryKnowledgeItem.Scope.PERSONAL, owner_user=item.owner_user)
            run.status = MemoryReflectionRun.Status.SUCCEEDED
            run.finished_at = timezone.now()
            run.metrics = {
                "created_candidates": len(candidates),
                "personal_items": personal_count,
                "organization_items": org_count,
                "queue_processed": False,
            }
            run.save(update_fields=["status", "finished_at", "metrics", "updated_at"])
        except Exception as exc:
            run.status = MemoryReflectionRun.Status.FAILED
            run.finished_at = timezone.now()
            run.error_message = str(exc)
            run.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
            raise

        self.stdout.write(self.style.SUCCESS(f"Knowledge reflection created {len(candidates)} candidate(s)."))
