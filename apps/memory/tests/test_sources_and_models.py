"""Тесты моделей источников, metadata и сервисов очереди."""
from apps.memory.tests._common import *  # noqa: F401,F403


class MemorySourceModelAndServiceTests(MemoryModelFactoryMixin, TestCase):
    databases = RUNTIME_DATABASES
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
