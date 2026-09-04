"""Тесты моделей источников, metadata и сервисов очереди."""
from types import SimpleNamespace

from apps.memory.tests._common import *  # noqa: F401,F403


class MemorySourceModelAndServiceTests(MemoryModelFactoryMixin, TestCase):
    databases = RUNTIME_DATABASES

    def test_source_lifecycle_fence_is_independent_from_access_lock(self):
        from apps.core.file_locks import (
            access_control_write_lock_path,
            exclusive_file_lock,
            memory_source_lifecycle_lock_path,
        )
        from apps.memory.source_lifecycle import enabled_source_operation

        source = self.create_source(code="independent-source-lifecycle-fence")
        with TemporaryDirectory() as tmpdir, self.settings(RUNTIME_CONTRACTS_DIR=Path(tmpdir)):
            access_path = access_control_write_lock_path()
            memory_path = memory_source_lifecycle_lock_path()
            with exclusive_file_lock(access_path, timeout=0.2):
                with enabled_source_operation(source_id=source.pk, timeout=0.2) as fresh_source:
                    self.assertEqual(fresh_source.pk, source.pk)
                    self.assertEqual(fresh_source.status, MemorySource.Status.ENABLED)

            self.assertNotEqual(access_path, memory_path)

    def test_memory_source_defaults_and_unique_code(self):
        source = self.create_source()

        self.assertEqual(source.status, MemorySource.Status.ENABLED)
        self.assertEqual(source.index_profiles, ["fulltext_default"])
        self.assertEqual(str(source), source.code)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_source(title="Duplicate source")

    def test_sync_sources_from_contract_upserts_enabled_and_disabled_sources(self):
        payload = [
            {
                "code": "workorders_public_timeline",
                "title": "Work orders public timeline",
                "source_kind": "django_model",
                "domain": "workorders",
                "owner": "operations",
                "enabled": True,
                "sync_mode": "incremental",
                "scope_rule": "workorder_visibility",
                "sensitivity": "internal",
                "pii_policy": "deidentify_before_index",
                "trust_status": "trusted",
                "authority_class": "system_of_record",
                "trusted_for_context": True,
                "requires_source_review": False,
                "review_owner": "operations",
                "trusted_context_kinds": ["retrieved_chunk", "citation"],
                "untrusted_handling": "review_required",
                "index_profiles": ["fulltext_default"],
            },
            {
                "code": "disabled_source",
                "title": "Disabled source",
                "source_kind": "file_tree",
                "domain": "docs",
                "enabled": False,
                "sensitivity": "public",
            },
        ]

        sources = sync_sources_from_contract(payload)

        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0].status, MemorySource.Status.ENABLED)
        self.assertEqual(sources[0].trust_status, MemorySource.TrustStatus.TRUSTED)
        self.assertEqual(sources[0].authority_class, MemorySource.AuthorityClass.SYSTEM_OF_RECORD)
        self.assertTrue(sources[0].trusted_for_context)
        self.assertEqual(sources[0].review_owner, "operations")
        self.assertEqual(sources[1].status, MemorySource.Status.DISABLED)
        self.assertEqual(sources[0].config["scope_rule"], "workorder_visibility")

    def test_full_source_sync_disables_omitted_projection_atomically_and_is_idempotent(self):
        stale = self.create_source(code="omitted-from-source-contract")
        payload = [{
            "code": "retained-source",
            "title": "Retained source",
            "source_kind": "django_model",
            "domain": "workorders",
            "sensitivity": "internal",
            "enabled": True,
        }]

        sync_sources_from_contract(payload)
        stale.refresh_from_db()
        self.assertEqual(stale.status, MemorySource.Status.DISABLED)
        self.assertEqual(stale.error_message, "source_missing_from_contract")
        self.assertFalse(
            MemorySource.objects.filter(
                code=stale.code, status=MemorySource.Status.ENABLED
            ).exists()
        )
        cleanup_jobs = MemoryExternalConnectorJob.objects.filter(
            job_kind=MemoryQueueJobKind.SOURCE_CLEANUP,
            source_code=stale.code,
        )
        self.assertEqual(cleanup_jobs.count(), 1)

        # A repeat of the same complete snapshot does not reopen the omitted
        # projection or create a second source row.
        sync_sources_from_contract(payload)
        self.assertEqual(MemorySource.objects.filter(code="retained-source").count(), 1)
        stale.refresh_from_db()
        self.assertEqual(stale.status, MemorySource.Status.DISABLED)
        self.assertEqual(cleanup_jobs.count(), 1)

    def test_source_scoped_sync_does_not_disable_other_projections(self):
        other = self.create_source(code="untouched-by-partial-source-sync")
        payload = [{
            "code": "partial-source",
            "title": "Partial source",
            "source_kind": "django_model",
            "domain": "workorders",
            "sensitivity": "internal",
            "enabled": True,
        }]

        sync_sources_from_contract(payload, source_code="partial-source")
        other.refresh_from_db()
        self.assertEqual(other.status, MemorySource.Status.ENABLED)
        self.assertEqual(other.error_message, "")

    def test_envelope_cannot_reenable_an_administratively_disabled_source(self):
        from apps.memory.services import _ensure_memory_source_from_envelope

        source = self.create_source(code="disabled-envelope-source")
        source.status = MemorySource.Status.DISABLED
        source.save(update_fields=["status", "updated_at"])
        envelope = SimpleNamespace(
            source_code=source.code,
            source_origin="internal",
            source_kind="django_model",
            domain="workorders",
            privacy_profile="pii_off",
            access_policy={},
            provenance={"adapter": source.code},
            schema_version="1.0",
            sensitivity="internal",
            title="Disabled source",
        )

        with self.assertRaises(ValidationError):
            _ensure_memory_source_from_envelope(envelope)
        source.refresh_from_db()
        self.assertEqual(source.status, MemorySource.Status.DISABLED)

    def test_delete_envelope_cannot_mutate_disabled_source(self):
        from apps.memory.services import delete_memory_projection_from_envelope

        source = self.create_source(code="disabled-delete-envelope")
        source_object = MemorySourceObject.objects.create(
            source=source,
            object_id="object-disabled-delete",
            object_uri="internal:disabled",
            relative_path="disabled.txt",
            file_name="disabled.txt",
            discovery_status=MemorySourceObject.DiscoveryStatus.SEEN,
            ingestion_status=MemorySourceObject.IngestionStatus.INGESTED,
        )
        source.status = MemorySource.Status.DISABLED
        source.save(update_fields=["status", "updated_at"])
        envelope = SimpleNamespace(source_code=source.code, object_id=source_object.object_id)

        with self.assertRaises(ValidationError):
            delete_memory_projection_from_envelope(envelope)
        source_object.refresh_from_db()
        self.assertEqual(source_object.discovery_status, MemorySourceObject.DiscoveryStatus.SEEN)
        self.assertEqual(source_object.ingestion_status, MemorySourceObject.IngestionStatus.INGESTED)

    def test_effective_source_trust_maps_legacy_statuses_to_mvp_statuses(self):
        cases = {
            MemorySource.TrustStatus.TRUSTED: "trusted",
            MemorySource.TrustStatus.CANDIDATE_ONLY: "review_required",
            MemorySource.TrustStatus.QUARANTINED: "review_required",
            MemorySource.TrustStatus.BLOCKED: "blocked",
            MemorySource.TrustStatus.REVIEW_REQUIRED: "review_required",
        }

        for raw_status, expected_status in cases.items():
            with self.subTest(raw_status=raw_status):
                source = self.create_source(code=f"trust_{raw_status}", trust_status=raw_status)
                decision = effective_source_trust(source)
                self.assertEqual(decision.raw_trust_status, raw_status)
                self.assertEqual(decision.trust_status, expected_status)


class MemoryMetadataModelTests(MemoryModelFactoryMixin, TestCase):
    databases = RUNTIME_DATABASES
    def test_memory_eval_case_creation_defaults_and_unique_code(self):
        eval_case = MemoryEvalCase.objects.create(
            code="smoke-workorder-search",
            title="Smoke workorder search",
            question="Find the safe work order context.",
            expected_source_codes=["workorders_public_timeline"],
            expected_document_ids=["document-1"],
            forbidden_source_codes=["patients_raw"],
            forbidden_scope_tokens=["pii:raw"],
        )

        self.assertEqual(eval_case.status, MemoryEvalCase.Status.ACTIVE)
        self.assertEqual(eval_case.suite, "smoke")
        self.assertEqual(eval_case.forbidden_scope_tokens, ["pii:raw"])
        self.assertEqual(str(eval_case), eval_case.code)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MemoryEvalCase.objects.create(
                    code="smoke-workorder-search",
                    title="Duplicate eval case",
                    question="Duplicate question",
                )


class MemoryQueueTaskServiceTests(MemoryModelFactoryMixin, TestCase):
    """Unified memory queue (ADR-0030 decision 2): single MemoryExternalConnectorJob table."""

    databases = RUNTIME_DATABASES

    def test_enqueue_lease_and_complete_task(self):
        source = self.create_source()

        job = enqueue_memory_queue_task(
            job_kind=MemoryQueueJobKind.REINDEX,
            source_code=source.code,
            idempotency_key="test-enqueue-1",
            payload={"source_code": source.code},
        )

        self.assertEqual(job.status, "pending")
        self.assertEqual(job.attempt_count, 0)
        self.assertEqual(job.max_attempts, 3)

        # Re-enqueueing with the same idempotency_key returns the same row.
        same_job = enqueue_memory_queue_task(
            job_kind=MemoryQueueJobKind.REINDEX,
            source_code=source.code,
            idempotency_key="test-enqueue-1",
            payload={"source_code": source.code},
        )
        self.assertEqual(same_job.pk, job.pk)
        self.assertEqual(MemoryExternalConnectorJob.objects.filter(idempotency_key="test-enqueue-1").count(), 1)

        leased = lease_memory_queue_tasks(job_kinds=[MemoryQueueJobKind.REINDEX], limit=5, locked_by="worker-1")
        self.assertEqual(len(leased), 1)
        self.assertEqual(leased[0].job_id, str(job.job_id))
        self.assertEqual(leased[0].locked_by, "worker-1")

        job.refresh_from_db()
        self.assertEqual(job.status, "running")
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(job.locked_by, "worker-1")

        complete_memory_queue_task(job.job_id, result={"indexed": True})
        job.refresh_from_db()
        self.assertEqual(job.status, "succeeded")
        self.assertEqual(job.result, {"indexed": True})
        self.assertEqual(job.error_message, "")
        self.assertEqual(job.locked_by, "")

    def test_failed_task_retries_then_reaches_dead_letter(self):
        job = enqueue_memory_queue_task(
            job_kind=MemoryQueueJobKind.REINDEX,
            idempotency_key="test-dead-letter-1",
            payload={"memory_id": "chat:personal:user-1:deadbeef"},
            max_attempts=2,
        )

        # Attempt 1: lease, fail -> retry_wait (attempts exhausted check is 1 < 2).
        leased = lease_memory_queue_tasks(job_kinds=[MemoryQueueJobKind.REINDEX], limit=1)
        self.assertEqual(len(leased), 1)
        failed = fail_memory_queue_task(leased[0].job_id, error_message="backend unavailable")
        self.assertEqual(failed.status, "retry_wait")
        job.refresh_from_db()
        self.assertEqual(job.attempt_count, 1)

        # Attempt 2: lease again (retry window elapses immediately in this
        # unit test because next_attempt_at is in the past by the time we
        # force it below), fail again -> attempt_count reaches max_attempts,
        # task moves to dead_letter and is visible to an operator.
        job.next_attempt_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["next_attempt_at"])
        leased_again = lease_memory_queue_tasks(job_kinds=[MemoryQueueJobKind.REINDEX], limit=1)
        self.assertEqual(len(leased_again), 1)
        final = fail_memory_queue_task(leased_again[0].job_id, error_message="backend unavailable again")
        self.assertEqual(final.status, "dead_letter")

        job.refresh_from_db()
        self.assertEqual(job.status, "dead_letter")
        self.assertEqual(job.attempt_count, job.max_attempts)
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(job.error_message, "backend unavailable again")

        # Dead-lettered tasks are not leased again.
        self.assertEqual(lease_memory_queue_tasks(job_kinds=[MemoryQueueJobKind.REINDEX], limit=5), [])
