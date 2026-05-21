from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.memory.chat_memory import process_queued_memory_requests, propose_reflection_candidates
from apps.memory.models import MemoryReflectionRun, MemoryWriteRequest
from apps.memory.policies import PUBLIC_SCOPE_TOKEN
from apps.memory.services import compile_knowledge_item_digest


class Command(BaseCommand):
    help = (
        "Compatibility command: process queued memory remember requests and propose organization "
        "memory candidates. This is not full nightly reflection."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show planned queue processing work without writing.")
        parser.add_argument("--limit", type=int, default=100, help="Maximum queued requests/items to process.")
        parser.add_argument("--window-hours", type=int, default=24, help="Compatibility reporting window size.")

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"]))
        dry_run = bool(options["dry_run"])
        now = timezone.now()
        window_start = now - timezone.timedelta(hours=max(1, int(options["window_hours"])))

        queued_count = MemoryWriteRequest.objects.filter(status=MemoryWriteRequest.Status.QUEUED).count()
        org_digest = compile_knowledge_item_digest(scope_tokens=[PUBLIC_SCOPE_TOKEN], limit=limit)
        if dry_run:
            self.stdout.write(
                "Memory queue processor dry-run: "
                f"queued_requests={queued_count}, candidate_scan_limit={limit}, "
                f"active_knowledge_digest_items={len(org_digest)}, window_start={window_start.isoformat()}"
            )
            return

        run = MemoryReflectionRun.objects.create(
            status=MemoryReflectionRun.Status.RUNNING,
            dry_run=False,
            window_start=window_start,
            window_end=now,
            started_at=timezone.now(),
        )
        try:
            processed = process_queued_memory_requests(limit=limit)
            candidates = propose_reflection_candidates(limit=limit)
            org_digest = compile_knowledge_item_digest(scope_tokens=[PUBLIC_SCOPE_TOKEN], limit=limit)
            run.status = MemoryReflectionRun.Status.SUCCEEDED
            run.finished_at = timezone.now()
            run.metrics = {
                "processed_requests": len(processed),
                "created_candidates": len(candidates),
                "active_knowledge_digest_items": len(org_digest),
                "digest_mode": "deterministic_only",
                "queued_at_start": queued_count,
                "compatibility_command": "memory_reflect_chats",
                "full_reflection": False,
            }
            run.save(update_fields=["status", "finished_at", "metrics", "updated_at"])
        except Exception as exc:
            run.status = MemoryReflectionRun.Status.FAILED
            run.finished_at = timezone.now()
            run.error_message = str(exc)
            run.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
            raise

        self.stdout.write(
            self.style.SUCCESS(
                "Memory queue processor succeeded: "
                f"processed_requests={len(processed)}, created_candidates={len(candidates)}"
            )
        )
