from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from apps.memory.models import MemoryChunk, MemoryGraphFact, MemoryIndexJob, MemorySnapshot, MemorySource
from apps.memory.services import create_index_job, mark_index_job_failed, mark_index_job_finished, mark_index_job_started


class Command(BaseCommand):
    help = "Run a backend-neutral MemoryIndexJob smoke reindex without Celery or raw PII indexing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-code",
            help="Limit the smoke reindex job to one MemorySource code.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Inspect eligible memory records without creating a MemoryIndexJob.",
        )

    def handle(self, *args, **options):
        source_code = (options.get("source_code") or "").strip()
        dry_run = bool(options.get("dry_run"))
        source = self._get_source(source_code) if source_code else None

        if dry_run:
            result = self._build_smoke_result(source=source)
            self.stdout.write(
                "Memory reindex dry-run: "
                f"sources={result['source_count']}, ready_snapshots={result['ready_snapshot_count']}, "
                f"active_chunks={result['active_chunk_count']}, active_graph_facts={result['active_graph_fact_count']}"
            )
            return

        job = create_index_job(
            job_kind=MemoryIndexJob.JobKind.REINDEX,
            source=source,
            payload={
                "source_code": source.code if source else "",
                "mode": "backend_neutral_smoke",
                "raw_pii_indexing": False,
                "celery": False,
            },
        )
        mark_index_job_started(job)
        try:
            result = self._build_smoke_result(source=source)
            mark_index_job_finished(job, result=result)
        except Exception as exc:
            mark_index_job_failed(job, error_message=str(exc), result={"mode": "backend_neutral_smoke"})
            raise

        self.stdout.write(
            self.style.SUCCESS(
                f"Memory reindex smoke job {job.pk} succeeded: "
                f"ready_snapshots={result['ready_snapshot_count']}, active_chunks={result['active_chunk_count']}"
            )
        )

    def _get_source(self, source_code):
        try:
            return MemorySource.objects.get(code=source_code)
        except MemorySource.DoesNotExist as exc:
            raise CommandError(f"MemorySource '{source_code}' does not exist. Run memory_sync_source first.") from exc

    def _build_smoke_result(self, *, source):
        sources = MemorySource.objects.all()
        snapshots = MemorySnapshot.objects.select_related("source").filter(is_active=True)
        chunks = MemoryChunk.objects.filter(is_active=True)
        facts = MemoryGraphFact.objects.filter(is_active=True)
        if source is not None:
            sources = sources.filter(pk=source.pk)
            snapshots = snapshots.filter(source=source)
            chunks = chunks.filter(snapshot__source=source)
            facts = facts.filter(snapshot__source=source)

        sensitivity_counts = {
            item["sensitivity"]: item["count"]
            for item in snapshots.values("sensitivity").annotate(count=Count("id")).order_by("sensitivity")
        }
        ready_snapshots = snapshots.filter(status=MemorySnapshot.Status.READY)
        missing_safe_path_count = ready_snapshots.filter(safe_path="").count()

        return {
            "mode": "backend_neutral_smoke",
            "raw_pii_indexing": False,
            "celery": False,
            "source_code": source.code if source else "",
            "source_count": sources.count(),
            "snapshot_count": snapshots.count(),
            "ready_snapshot_count": ready_snapshots.count(),
            "blocked_snapshot_count": snapshots.filter(status=MemorySnapshot.Status.BLOCKED).count(),
            "failed_snapshot_count": snapshots.filter(status=MemorySnapshot.Status.FAILED).count(),
            "active_chunk_count": chunks.count(),
            "active_graph_fact_count": facts.count(),
            "ready_snapshots_missing_safe_path": missing_safe_path_count,
            "sensitivity_counts": sensitivity_counts,
        }
