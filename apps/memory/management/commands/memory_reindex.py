from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.memory.models import MemoryIndexJob, MemorySearchDocument, MemorySource
from apps.memory.policies import search_document_sensitivity
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
                f"sources={result['source_count']}, ready_documents={result['ready_document_count']}, "
                f"knowledge_documents={result['knowledge_document_count']}, source_data_documents={result['source_data_document_count']}"
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
                f"ready_documents={result['ready_document_count']}"
            )
        )

    def _get_source(self, source_code):
        try:
            return MemorySource.objects.get(code=source_code)
        except MemorySource.DoesNotExist as exc:
            raise CommandError(f"MemorySource '{source_code}' does not exist. Run memory_sync_source first.") from exc

    def _build_smoke_result(self, *, source):
        sources = MemorySource.objects.all()
        documents = MemorySearchDocument.objects.filter(index_status=MemorySearchDocument.IndexStatus.READY)
        if source is not None:
            sources = sources.filter(pk=source.pk)
            documents = documents.filter(Q(source_object__source=source) | Q(knowledge_item__source_code=source.code))

        sensitivity_counts = {}
        for document in documents.select_related("knowledge_item", "source_object", "source_object__source"):
            sensitivity = search_document_sensitivity(document)
            sensitivity_counts[sensitivity] = sensitivity_counts.get(sensitivity, 0) + 1

        return {
            "mode": "backend_neutral_smoke",
            "raw_pii_indexing": False,
            "celery": False,
            "source_code": source.code if source else "",
            "source_count": sources.count(),
            "document_count": documents.count(),
            "ready_document_count": documents.count(),
            "knowledge_document_count": documents.filter(corpus_type=MemorySearchDocument.CorpusType.KNOWLEDGE).count(),
            "source_data_document_count": documents.filter(corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA).count(),
            "sensitivity_counts": sensitivity_counts,
        }
