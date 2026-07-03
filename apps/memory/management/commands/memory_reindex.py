from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.memory.chat_memory import index_knowledge_item
from apps.memory.document_ingestion import (
    delete_search_document_indexes,
    get_source_ingestion_profile,
    ingest_source_object_text,
    inspect_source_object_for_ingestion,
)
from apps.memory.models import MemoryIndexJob, MemoryIngestionIssue, MemorySearchDocument, MemorySource, MemorySourceObject
from apps.memory.policies import search_document_sensitivity
from apps.memory.services import create_index_job, mark_index_job_failed, mark_index_job_finished, mark_index_job_started
from apps.memory.source_text_extraction import PARSER_VERSION
from apps.memory.vector_backends import LANCEDB_VECTOR_SCHEMA_VERSION, get_default_fulltext_schema_version


def backend_versions():
    return {
        "fulltext": get_default_fulltext_schema_version(),
        "vector": LANCEDB_VECTOR_SCHEMA_VERSION,
    }


class Command(BaseCommand):
    help = "Rebuild memory search indexes for knowledge and source_data documents."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", help="Limit reindex to one MemorySource code.")
        parser.add_argument(
            "--corpus",
            choices=("knowledge", "source_data", "all"),
            default="all",
            help="Corpus to reindex.",
        )
        parser.add_argument(
            "--backend",
            choices=("fulltext", "vector", "all"),
            default="all",
            help="Index backend to rebuild.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Inspect eligible records without writing indexes or creating a MemoryIndexJob.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Reindex even if content hash and index versions look current.",
        )

    def handle(self, *args, **options):
        source_code = (options.get("source_code") or "").strip()
        source = self._get_source(source_code) if source_code else None
        corpus = options["corpus"]
        backend = options["backend"]
        backends = ("fulltext", "vector") if backend == "all" else (backend,)
        dry_run = bool(options.get("dry_run"))
        force = bool(options.get("force"))

        if dry_run:
            result = self._run_reindex(source=source, corpus=corpus, backends=backends, force=force, dry_run=True)
            self.stdout.write(
                "Memory reindex dry-run: "
                f"corpus={corpus}, backend={backend}, eligible={result['eligible_document_count']}, "
                f"would_index={result['would_index_count']}, skipped_current={result['skipped_current_count']}, "
                f"failed={result['failed_document_count']}"
            )
            return

        job = create_index_job(
            job_kind=MemoryIndexJob.JobKind.REINDEX,
            source=source,
            payload={
                "source_code": source.code if source else "",
                "corpus": corpus,
                "backend": backend,
                "force": force,
                "raw_pii_indexing": False,
                "celery": False,
            },
        )
        mark_index_job_started(job)
        try:
            result = self._run_reindex(source=source, corpus=corpus, backends=backends, force=force, dry_run=False)
            mark_index_job_finished(job, result=result)
        except Exception as exc:
            mark_index_job_failed(job, error_message=str(exc), result={"corpus": corpus, "backend": backend})
            raise

        self.stdout.write(
            self.style.SUCCESS(
                f"Memory reindex job {job.pk} succeeded: indexed={result['indexed_document_count']}, "
                f"skipped_current={result['skipped_current_count']}, failed={result['failed_document_count']}"
            )
        )

    def _get_source(self, source_code):
        try:
            return MemorySource.objects.get(code=source_code)
        except MemorySource.DoesNotExist as exc:
            raise CommandError(f"MemorySource '{source_code}' does not exist. Run memory_sync_source first.") from exc

    def _run_reindex(self, *, source, corpus, backends, force, dry_run):
        documents = MemorySearchDocument.objects.select_related("knowledge_item", "source_object", "source_object__source").filter(
            index_status=MemorySearchDocument.IndexStatus.READY
        )
        if corpus != "all":
            documents = documents.filter(corpus_type=corpus)
        if source is not None:
            documents = documents.filter(Q(source_object__source=source) | Q(knowledge_item__source_code=source.code))

        result = {
            "mode": "reindex",
            "raw_pii_indexing": False,
            "celery": False,
            "source_code": source.code if source else "",
            "corpus": corpus,
            "backends": list(backends),
            "force": force,
            "eligible_document_count": 0,
            "would_index_count": 0,
            "indexed_document_count": 0,
            "skipped_current_count": 0,
            "failed_document_count": 0,
            "blocked_secret_count": 0,
            "pii_audit_count": 0,
            "deleted_document_count": 0,
            "knowledge_document_count": 0,
            "source_data_document_count": 0,
            "sensitivity_counts": {},
        }
        if not dry_run and corpus in {"source_data", "all"}:
            result["deleted_document_count"] = _delete_missing_source_documents(source=source, backends=backends)

        for document in documents.order_by("corpus_type", "document_id"):
            result["eligible_document_count"] += 1
            result[f"{document.corpus_type}_document_count"] += 1
            sensitivity = search_document_sensitivity(document)
            result["sensitivity_counts"][sensitivity] = result["sensitivity_counts"].get(sensitivity, 0) + 1

            if not force and not _needs_reindex(document, backends=backends):
                result["skipped_current_count"] += 1
                continue
            result["would_index_count"] += 1
            if dry_run:
                continue
            try:
                if document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE:
                    if document.knowledge_item_id is None:
                        raise CommandError(f"Knowledge document {document.document_id} has no knowledge item.")
                    index_knowledge_item(document.knowledge_item, index_backends=backends)
                else:
                    if document.source_object_id is None:
                        raise CommandError(f"Source document {document.document_id} has no source object.")
                    source_object = document.source_object
                    if not source_object.object_uri:
                        raise CommandError(f"Source object {source_object.object_id} has no object_uri.")
                    profile = get_source_ingestion_profile(source_object.source)
                    outcome = inspect_source_object_for_ingestion(source_object=source_object, profile=profile)
                    if outcome["status"] in {
                        source_object.IngestionStatus.SKIPPED,
                        source_object.IngestionStatus.FAILED,
                    }:
                        if outcome["issue_kind"] == MemoryIngestionIssue.IssueKind.SECRET_BLOCKED:
                            _block_secret_document(document=document, outcome=outcome, backends=backends)
                            result["blocked_secret_count"] += 1
                            result["failed_document_count"] += 1
                            continue
                        raise CommandError(outcome["message"] or f"Source object {source_object.object_id} is not indexable.")
                    if outcome["issue_kind"] == MemoryIngestionIssue.IssueKind.PII_AUDIT:
                        _create_reindex_issue(document=document, outcome=outcome)
                        result["pii_audit_count"] += 1
                    ingest_source_object_text(
                        source_object=source_object,
                        safe_text=outcome["text"],
                        partial_reason=outcome["partial_reason"],
                        extraction_metadata=outcome["metadata"].get("extraction"),
                        index_backends=backends,
                    )
                result["indexed_document_count"] += 1
            except Exception:
                result["failed_document_count"] += 1
                MemorySearchDocument.objects.filter(pk=document.pk).update(index_status=MemorySearchDocument.IndexStatus.FAILED)
        return result


def _needs_reindex(document: MemorySearchDocument, *, backends) -> bool:
    metadata = document.metadata or {}
    versions = metadata.get("index_versions") or {}
    expected_versions = backend_versions()
    for backend in backends:
        if versions.get(backend) != expected_versions[backend]:
            return True
    if document.corpus_type == MemorySearchDocument.CorpusType.SOURCE_DATA:
        if metadata.get("content_hash") != document.source_object.content_hash:
            return True
        if metadata.get("acl_fingerprint") != document.source_object.acl_fingerprint:
            return True
        source = document.source_object.source
        if metadata.get("sensitivity") != source.sensitivity:
            return True
        if metadata.get("trust_status") != source.trust_status:
            return True
        if metadata.get("authority_class") != source.authority_class:
            return True
        extraction = metadata.get("extraction") or {}
        if extraction.get("parser") != PARSER_VERSION:
            return True
        embedding = metadata.get("embedding") or {}
        if "vector" in backends and embedding.get("version") != _current_embedding_version():
            return True
    if document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE and document.knowledge_item_id:
        if document.body_hash != document.knowledge_item.text_hash:
            return True
    return False


def _current_embedding_version() -> str:
    vector_backend = None
    try:
        from apps.memory.vector_backends import get_default_vector_backend

        vector_backend = get_default_vector_backend()
    except Exception:
        return ""
    if vector_backend is None:
        return ""
    return vector_backend.embedding_provider.metadata.version


def _delete_missing_source_documents(*, source, backends) -> int:
    queryset = MemorySearchDocument.objects.filter(
        corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA,
        source_object__discovery_status=MemorySourceObject.DiscoveryStatus.MISSING,
    ).exclude(index_status=MemorySearchDocument.IndexStatus.DELETED)
    if source is not None:
        queryset = queryset.filter(source_object__source=source)
    document_ids = list(queryset.values_list("document_id", flat=True))
    if not document_ids:
        return 0
    delete_search_document_indexes(document_ids, index_backends=backends)
    queryset.update(index_status=MemorySearchDocument.IndexStatus.DELETED)
    return len(document_ids)


def _block_secret_document(*, document: MemorySearchDocument, outcome: dict, backends) -> None:
    delete_search_document_indexes([document.document_id], index_backends=backends)
    _create_reindex_issue(document=document, outcome=outcome)
    document.index_status = MemorySearchDocument.IndexStatus.FAILED
    metadata = dict(document.metadata or {})
    metadata["blocked_reason"] = "secret_detected"
    document.metadata = metadata
    document.save(update_fields=["index_status", "metadata", "updated_at"])


def _create_reindex_issue(*, document: MemorySearchDocument, outcome: dict) -> None:
    source_object = document.source_object
    if source_object is None:
        return
    MemoryIngestionIssue.objects.create(
        source=source_object.source,
        source_object=source_object,
        issue_kind=outcome["issue_kind"],
        severity=outcome["severity"],
        message=outcome["message"],
        metadata=outcome.get("metadata") or {},
    )
