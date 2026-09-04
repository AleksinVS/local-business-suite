"""Post-commit scheduling for database-backed memory setting revisions."""

from copy import deepcopy
from unittest import skipUnless
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.db import transaction
from django.core.management import call_command
from django.test import TransactionTestCase, override_settings
import pytest

from apps.memory.models import MemoryExternalConnectorJob, MemorySearchDocument, MemorySource, MemorySourceObject
from apps.memory.services import MemoryQueueJobKind
from apps.settings_center.document_registry import get_document_registry
from apps.settings_center.document_repository import ConfigDocumentRepository
from apps.settings_center.document_services import ConfigDocumentWriter
from apps.settings_center.document_services import ExpectedDocumentVersion


pytestmark = pytest.mark.integration

MEMORY_REINDEX_DATABASE_SLICE = (
    "memory.contract.sources",
    "memory.contract.profiles",
    "memory.contract.routing",
    "memory.contract.ingestion_profiles",
)

@skipUnless(connection.vendor == "postgresql", "Требуется PostgreSQL")
@override_settings(
    # The writer validates the full connected source/profile/routing/ingestion
    # component, so the test opts into that complete released slice.
    LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST=MEMORY_REINDEX_DATABASE_SLICE,
)
class MemorySettingsReindexPostCommitTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        # The registry is cached, and this class deliberately opts into the
        # released memory database slice for a real PostgreSQL writer test.
        get_document_registry.cache_clear()
        super().setUpClass()
        get_document_registry.cache_clear()

    @classmethod
    def tearDownClass(cls):
        get_document_registry.cache_clear()
        super().tearDownClass()
        get_document_registry.cache_clear()

    def setUp(self):
        self.spec = get_document_registry().get("memory.contract.profiles")
        if self.spec.active_backend != "database":
            self.skipTest("Memory database override slice is not enabled in this deployment.")
        self.actor = self._user()
        self.repository = ConfigDocumentRepository()
        self.writer = ConfigDocumentWriter()

    @staticmethod
    def _user():
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_superuser(
            username="memory-settings-reindex", password="x"
        )

    def _candidate(self):
        current = self.repository.get_document(self.spec.document_id)
        candidate = deepcopy(current.payload)
        profile = candidate["ranking_profiles"]["precise"]
        profile["max_results"] = int(profile.get("max_results", 12)) + 1
        return current, candidate

    def test_rollback_does_not_leave_reindex_job(self):
        current, candidate = self._candidate()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.writer.save_document(
                    actor=self.actor,
                    document_id=self.spec.document_id,
                    payload=candidate,
                    expected_revision=current.revision,
                    expected_content_hash=current.content_hash,
                )
                raise RuntimeError("rollback test")
        self.assertFalse(
            MemoryExternalConnectorJob.objects.filter(
                idempotency_key__startswith="settings-memory-reindex:memory.contract.profiles:"
            ).exists()
        )

    def test_success_enqueues_one_revision_key_after_commit(self):
        current, candidate = self._candidate()
        snapshot = self.writer.save_document(
            actor=self.actor,
            document_id=self.spec.document_id,
            payload=candidate,
            expected_revision=current.revision,
            expected_content_hash=current.content_hash,
        )
        jobs = MemoryExternalConnectorJob.objects.filter(
            idempotency_key=(
                "settings-memory-reindex:memory.contract.profiles:"
                f"{snapshot.revision}:{snapshot.content_hash}"
            )
        )
        self.assertEqual(jobs.count(), 1)
        self.assertEqual(jobs.get().payload["document_revision"], snapshot.revision)

        # The same revision is safely idempotent if a duplicate callback is
        # delivered by an outer transaction boundary.
        from apps.memory.services import enqueue_memory_reindex_for_document_revision

        enqueue_memory_reindex_for_document_revision(
            document_id=snapshot.document_id,
            revision=snapshot.revision,
            content_hash=snapshot.content_hash,
            change_id=snapshot.change_id,
        )
        self.assertEqual(jobs.count(), 1)

    def test_settings_change_failure_does_not_leave_reindex_job(self):
        current, candidate = self._candidate()
        with patch(
            "apps.settings_center.document_services.SettingsChange.objects.create",
            side_effect=IntegrityError("settings audit failure"),
        ):
            with self.assertRaises(IntegrityError):
                self.writer.save_document(
                    actor=self.actor,
                    document_id=self.spec.document_id,
                    payload=candidate,
                    expected_revision=current.revision,
                    expected_content_hash=current.content_hash,
                )
        self.assertFalse(
            MemoryExternalConnectorJob.objects.filter(
                idempotency_key__startswith="settings-memory-reindex:memory.contract.profiles:"
            ).exists()
        )

    def test_outbox_insert_failure_rolls_back_document_and_audit(self):
        current, candidate = self._candidate()
        with patch(
            "apps.memory.services.enqueue_memory_queue_task",
            side_effect=IntegrityError("outbox insert failure"),
        ):
            with self.assertRaises(IntegrityError):
                self.writer.save_document(
                    actor=self.actor,
                    document_id=self.spec.document_id,
                    payload=candidate,
                    expected_revision=current.revision,
                    expected_content_hash=current.content_hash,
                )
        self.assertEqual(
            self.repository.get_fresh_document(self.spec.document_id).revision,
            current.revision,
        )
        self.assertFalse(
            MemoryExternalConnectorJob.objects.filter(
                idempotency_key__startswith="settings-memory-reindex:memory.contract.profiles:"
            ).exists()
        )

    def test_domain_rollback_enqueues_the_rollback_revision(self):
        current, candidate = self._candidate()
        applied = self.writer.save_document(
            actor=self.actor,
            document_id=self.spec.document_id,
            payload=candidate,
            expected_revision=current.revision,
            expected_content_hash=current.content_hash,
        )
        rolled_back = self.writer.rollback_document(
            actor=self.actor,
            document_id=self.spec.document_id,
            source_change_id=applied.change_id,
            expected_revision=applied.revision,
            expected_content_hash=applied.content_hash,
        )
        keys = list(
            MemoryExternalConnectorJob.objects.filter(
                idempotency_key__startswith="settings-memory-reindex:memory.contract.profiles:"
            ).values_list("idempotency_key", flat=True)
        )
        self.assertEqual(len(keys), 2)
        self.assertTrue(
            any(f":{applied.revision}:{applied.content_hash}" in key for key in keys)
        )
        self.assertTrue(
            any(f":{rolled_back.revision}:{rolled_back.content_hash}" in key for key in keys)
        )

    def test_batch_writer_creates_one_outbox_row_per_changed_document(self):
        source_spec = get_document_registry().get("memory.contract.sources")
        source = self.repository.get_document(source_spec.document_id)
        profile = self.repository.get_document(self.spec.document_id)
        source_candidate = deepcopy(source.payload)
        source_candidate[0]["description"] = (
            source_candidate[0].get("description", "") + " batch-test"
        )
        profile_candidate = deepcopy(profile.payload)
        profile_candidate["ranking_profiles"]["precise"]["max_results"] = (
            int(profile_candidate["ranking_profiles"]["precise"].get("max_results", 12)) + 1
        )
        result = self.writer._save_documents(
            actor=self.actor,
            candidates={
                source_spec.document_id: source_candidate,
                self.spec.document_id: profile_candidate,
            },
            expected={
                source_spec.document_id: ExpectedDocumentVersion(
                    source.revision, source.content_hash
                ),
                self.spec.document_id: ExpectedDocumentVersion(
                    profile.revision, profile.content_hash
                ),
            },
            locked_authorize=lambda: self.actor,
        )
        self.assertEqual(set(result), {source_spec.document_id, self.spec.document_id})
        self.assertEqual(
            MemoryExternalConnectorJob.objects.filter(
                job_kind="reindex",
                idempotency_key__startswith="settings-memory-reindex:",
            ).count(),
            2,
        )

    def test_sources_revision_worker_syncs_projection_and_cleanup_idempotently(self):
        source_spec = get_document_registry().get("memory.contract.sources")
        current = self.repository.get_document(source_spec.document_id)
        source_item = deepcopy(current.payload[-1])
        retired_code = source_item["code"]
        stale = MemorySource.objects.create(
            code=retired_code,
            title=source_item["title"],
            source_kind=source_item["source_kind"],
            domain=source_item["domain"],
            owner=source_item.get("owner", ""),
            status=MemorySource.Status.ENABLED,
            trust_status=source_item.get("trust_status", ""),
            authority_class=source_item.get("authority_class", ""),
            trusted_for_context=bool(source_item.get("trusted_for_context", False)),
            requires_source_review=bool(source_item.get("requires_source_review", True)),
            review_owner=source_item.get("review_owner", ""),
            trusted_context_kinds=source_item.get("trusted_context_kinds", []),
            untrusted_handling=source_item.get("untrusted_handling", ""),
            sync_mode=source_item.get("sync_mode", ""),
            scope_rule=source_item.get("scope_rule", ""),
            sensitivity=source_item["sensitivity"],
            pii_policy=source_item.get("pii_policy", ""),
            extractor_profile=source_item.get("extractor_profile", ""),
            chunking_profile=source_item.get("chunking_profile", ""),
            index_profiles=source_item.get("index_profiles", []),
            config=source_item,
        )
        source_object = MemorySourceObject.objects.create(
            source=stale,
            object_id="retired-object",
            object_uri="file:retired-object",
            relative_path="retired.txt",
            file_name="retired.txt",
            discovery_status=MemorySourceObject.DiscoveryStatus.SEEN,
            ingestion_status=MemorySourceObject.IngestionStatus.INGESTED,
        )
        document = MemorySearchDocument.objects.create(
            document_id="source:retired-object",
            corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA,
            object_kind=MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
            source_object=source_object,
            body_hash="retired-hash",
            index_status=MemorySearchDocument.IndexStatus.READY,
        )
        candidate = deepcopy(current.payload[:-1])
        applied = self.writer.save_document(
            actor=self.actor,
            document_id=source_spec.document_id,
            payload=candidate,
            expected_revision=current.revision,
            expected_content_hash=current.content_hash,
        )
        with patch(
            "apps.memory.management.commands.memory_queue_worker._process_reconcile",
            return_value={"reconciled": True},
        ):
            call_command("memory_queue_worker", "--limit", "1", verbosity=0)
        stale.refresh_from_db()
        self.assertEqual(stale.status, MemorySource.Status.DISABLED)
        cleanup = MemoryExternalConnectorJob.objects.get(
            job_kind=MemoryQueueJobKind.SOURCE_CLEANUP,
            source_code=retired_code,
        )
        self.assertEqual(cleanup.status, "pending")
        with patch("apps.memory.services.delete_search_document_indexes", return_value={}):
            call_command("memory_queue_worker", "--limit", "1", verbosity=0)
        cleanup.refresh_from_db()
        self.assertEqual(cleanup.status, "succeeded", cleanup.error_message)
        document.refresh_from_db()
        source_object.refresh_from_db()
        self.assertEqual(document.index_status, MemorySearchDocument.IndexStatus.DELETED)
        self.assertEqual(source_object.discovery_status, MemorySourceObject.DiscoveryStatus.MISSING)
        self.assertEqual(
            MemoryExternalConnectorJob.objects.filter(
                job_kind=MemoryQueueJobKind.SOURCE_CLEANUP,
                source_code=retired_code,
            ).count(),
            1,
        )
        # A second complete sync sees an already-disabled projection and does
        # not enqueue another cleanup task.
        from apps.memory.services import sync_sources_from_contract

        sync_sources_from_contract(candidate)
        self.assertEqual(
            MemoryExternalConnectorJob.objects.filter(
                job_kind=MemoryQueueJobKind.SOURCE_CLEANUP,
                source_code=retired_code,
            ).count(),
            1,
        )
