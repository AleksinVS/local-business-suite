from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .admin import (
    MemoryAccessAuditAdmin,
    MemoryChunkAdmin,
    MemoryEvalCaseAdmin,
    MemoryGraphFactAdmin,
    MemoryIndexJobAdmin,
    MemorySnapshotAdmin,
    MemorySourceAdmin,
)
from .models import (
    MemoryAccessAudit,
    MemoryChunk,
    MemoryEvalCase,
    MemoryGraphFact,
    MemoryIndexJob,
    MemorySnapshot,
    MemorySource,
)
from .policies import can_access_chunk, can_access_graph_fact, can_manage_memory, user_scope_tokens
from .services import (
    apply_snapshot_privacy_pipeline,
    create_index_job,
    deactivate_snapshot_memory_indexes,
    index_ready_snapshot_text,
    mark_index_job_failed,
    mark_index_job_finished,
    mark_index_job_started,
    record_access_audit,
    sync_sources_from_contract,
)

User = get_user_model()


class MemoryModelFactoryMixin:
    def create_source(self, code="workorders_public_timeline", **overrides):
        defaults = {
            "code": code,
            "title": "Work orders public timeline",
            "source_kind": "django_model",
            "domain": "workorders",
            "owner": "operations",
            "sensitivity": "internal",
            "pii_policy": "deidentify_before_index",
            "index_profiles": ["vector_default", "graph_default"],
        }
        defaults.update(overrides)
        return MemorySource.objects.create(**defaults)

    def create_snapshot(self, source=None, source_object_id="wo-1", content_hash="hash-1", **overrides):
        defaults = {
            "source": source or self.create_source(),
            "source_object_id": source_object_id,
            "content_hash": content_hash,
            "schema_version": "memory-source-v1",
            "extractor_version": "extractor-v1",
            "extracted_at": timezone.now(),
            "raw_path": "data/memory/raw_vault/workorders/wo-1.json",
            "safe_path": "data/memory/safe_corpus/workorders/wo-1.json",
            "pii_policy_applied": "deidentify_before_index",
            "scope_tokens": ["org:default"],
            "sensitivity": "internal",
            "metadata": {"source_title": "Work order 1"},
        }
        defaults.update(overrides)
        return MemorySnapshot.objects.create(**defaults)

    def create_chunk(self, snapshot=None, chunk_id="chunk-1", position=0, **overrides):
        snapshot = snapshot or self.create_snapshot()
        defaults = {
            "snapshot": snapshot,
            "chunk_id": chunk_id,
            "source_code": snapshot.source.code,
            "source_object_id": snapshot.source_object_id,
            "snapshot_hash": snapshot.content_hash,
            "position": position,
            "text_path": "data/memory/safe_corpus/workorders/wo-1/chunk-1.txt",
            "text_hash": "text-hash-1",
            "metadata": {"section": "timeline"},
            "scope_tokens": ["org:default"],
            "sensitivity": "internal",
        }
        defaults.update(overrides)
        return MemoryChunk.objects.create(**defaults)

    def create_fact(self, chunk=None, fact_id="fact-1", **overrides):
        chunk = chunk or self.create_chunk()
        defaults = {
            "fact_id": fact_id,
            "source_chunk": chunk,
            "snapshot": chunk.snapshot,
            "snapshot_hash": chunk.snapshot_hash,
            "subject_id": "device:1",
            "predicate": "has_work_order",
            "object_id": "workorder:1",
            "subject_type": "device",
            "object_type": "workorder",
            "confidence": "0.9000",
            "extracted_by": "graph-extractor-v1",
            "metadata": {"evidence": chunk.chunk_id},
            "scope_tokens": ["org:default"],
            "sensitivity": "internal",
        }
        defaults.update(overrides)
        return MemoryGraphFact.objects.create(**defaults)


class MemoryAdminObservabilityTests(TestCase):
    def test_memory_admin_registers_observability_models(self):
        expected_admin_classes = {
            MemorySource: MemorySourceAdmin,
            MemorySnapshot: MemorySnapshotAdmin,
            MemoryChunk: MemoryChunkAdmin,
            MemoryGraphFact: MemoryGraphFactAdmin,
            MemoryIndexJob: MemoryIndexJobAdmin,
            MemoryAccessAudit: MemoryAccessAuditAdmin,
            MemoryEvalCase: MemoryEvalCaseAdmin,
        }

        for model, admin_class in expected_admin_classes.items():
            with self.subTest(model=model.__name__):
                self.assertIsInstance(django_admin.site._registry[model], admin_class)

    def test_memory_admin_search_fields_do_not_include_storage_paths(self):
        path_fields = {"raw_path", "safe_path", "text_path"}

        for model in (
            MemorySource,
            MemorySnapshot,
            MemoryChunk,
            MemoryGraphFact,
            MemoryIndexJob,
            MemoryAccessAudit,
            MemoryEvalCase,
        ):
            with self.subTest(model=model.__name__):
                model_admin = django_admin.site._registry[model]
                self.assertTrue(path_fields.isdisjoint(model_admin.search_fields))


class MemorySourceModelAndServiceTests(MemoryModelFactoryMixin, TestCase):
    def test_memory_source_defaults_and_unique_code(self):
        source = self.create_source()

        self.assertEqual(source.status, MemorySource.Status.ENABLED)
        self.assertEqual(source.index_profiles, ["vector_default", "graph_default"])
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
                "index_profiles": ["vector_default"],
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
        self.assertEqual(sources[1].status, MemorySource.Status.DISABLED)
        self.assertEqual(sources[0].config["scope_rule"], "workorder_visibility")


class MemoryMetadataModelTests(MemoryModelFactoryMixin, TestCase):
    def test_memory_snapshot_creation_defaults_provenance_and_active_uniqueness(self):
        source = self.create_source()
        snapshot = self.create_snapshot(source=source)

        self.assertEqual(snapshot.status, MemorySnapshot.Status.READY)
        self.assertTrue(snapshot.is_active)
        self.assertEqual(snapshot.source, source)
        self.assertEqual(snapshot.pii_policy_applied, "deidentify_before_index")
        self.assertIn("data/memory/raw_vault/", snapshot.raw_path)
        self.assertIn("data/memory/safe_corpus/", snapshot.safe_path)
        self.assertEqual(str(snapshot), f"{source.code}:wo-1@hash-1")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_snapshot(source=source, content_hash="hash-2")

        snapshot.is_active = False
        snapshot.save(update_fields=["is_active", "updated_at"])
        replacement = self.create_snapshot(source=source, content_hash="hash-2")
        self.assertTrue(replacement.is_active)

    def test_memory_chunk_creation_defaults_provenance_and_position_uniqueness(self):
        snapshot = self.create_snapshot()
        chunk = self.create_chunk(snapshot=snapshot)

        self.assertTrue(chunk.is_active)
        self.assertEqual(chunk.source_code, snapshot.source.code)
        self.assertEqual(chunk.source_object_id, snapshot.source_object_id)
        self.assertEqual(chunk.snapshot_hash, snapshot.content_hash)
        self.assertEqual(chunk.scope_tokens, ["org:default"])
        self.assertNotIn("text", {field.name for field in MemoryChunk._meta.fields if field.name not in {"text_path", "text_hash"}})

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_chunk(snapshot=snapshot, chunk_id="chunk-2", position=0)

    def test_memory_graph_fact_creation_defaults_provenance_and_confidence_bounds(self):
        chunk = self.create_chunk()
        fact = self.create_fact(chunk=chunk)

        self.assertTrue(fact.is_active)
        self.assertEqual(fact.source_chunk, chunk)
        self.assertEqual(fact.snapshot, chunk.snapshot)
        self.assertEqual(fact.snapshot_hash, chunk.snapshot_hash)
        self.assertEqual(fact.extracted_by, "graph-extractor-v1")
        self.assertEqual(str(fact), "fact-1")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_fact(chunk=chunk, fact_id="fact-invalid", confidence="1.2500")

    def test_memory_eval_case_creation_defaults_and_unique_code(self):
        eval_case = MemoryEvalCase.objects.create(
            code="smoke-workorder-search",
            title="Smoke workorder search",
            question="Find the safe work order context.",
            expected_source_codes=["workorders_public_timeline"],
            expected_chunk_ids=["chunk-1"],
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


class MemoryIndexJobServiceTests(MemoryModelFactoryMixin, TestCase):
    def test_create_and_transition_index_job(self):
        user = User.objects.create_user(username="memory-indexer", password="pass")
        source = self.create_source()

        job = create_index_job(
            job_kind=MemoryIndexJob.JobKind.SYNC,
            source=source,
            created_by=user,
            request_id="req-1",
            payload={"source_code": source.code},
        )

        self.assertEqual(job.status, MemoryIndexJob.Status.PENDING)
        self.assertEqual(job.attempts, 0)
        self.assertEqual(job.max_attempts, 3)
        self.assertEqual(str(job), f"sync:pending:{job.pk}")

        mark_index_job_started(job)
        job.refresh_from_db()
        self.assertEqual(job.status, MemoryIndexJob.Status.RUNNING)
        self.assertEqual(job.attempts, 1)
        self.assertIsNotNone(job.started_at)

        mark_index_job_finished(job, result={"chunks": 1})
        job.refresh_from_db()
        self.assertEqual(job.status, MemoryIndexJob.Status.SUCCEEDED)
        self.assertEqual(job.result, {"chunks": 1})
        self.assertEqual(job.error_message, "")
        self.assertIsNotNone(job.finished_at)

    def test_mark_index_job_failed_records_error_and_result(self):
        job = create_index_job(job_kind=MemoryIndexJob.JobKind.REINDEX)

        mark_index_job_started(job)
        mark_index_job_failed(job, error_message="backend unavailable", result={"retryable": True})
        job.refresh_from_db()

        self.assertEqual(job.status, MemoryIndexJob.Status.FAILED)
        self.assertEqual(job.error_message, "backend unavailable")
        self.assertEqual(job.result, {"retryable": True})
        self.assertIsNotNone(job.finished_at)


class MemoryPolicyAndAuditTests(MemoryModelFactoryMixin, TestCase):
    def test_user_scope_tokens_and_manage_policy(self):
        group = Group.objects.create(name="memory_admins")
        user = User.objects.create_user(username="memory-user", password="pass", is_staff=True)
        user.groups.add(group)

        tokens = user_scope_tokens(user)

        self.assertIn("org:default", tokens)
        self.assertIn(f"user:{user.id}", tokens)
        self.assertIn("role:memory_admins", tokens)
        self.assertTrue(can_manage_memory(user))
        self.assertFalse(can_manage_memory(User(username="anonymous")))

    def test_chunk_and_graph_fact_access_respects_scope_activity_and_superuser(self):
        user = User.objects.create_user(username="scoped-user", password="pass")
        superuser = User.objects.create_superuser(username="memory-root", password="pass")
        chunk = self.create_chunk(scope_tokens=[f"user:{user.id}"])
        fact = self.create_fact(chunk=chunk, scope_tokens=[f"user:{user.id}"])

        self.assertTrue(can_access_chunk(user, chunk))
        self.assertTrue(can_access_graph_fact(user, fact))

        chunk.is_active = False
        chunk.save(update_fields=["is_active", "updated_at"])
        fact.is_active = False
        fact.save(update_fields=["is_active", "updated_at"])

        self.assertFalse(can_access_chunk(user, chunk))
        self.assertFalse(can_access_graph_fact(user, fact))
        self.assertTrue(can_access_chunk(superuser, chunk))
        self.assertTrue(can_access_graph_fact(superuser, fact))

    def test_record_access_audit_uses_hashes_ids_and_scope_tokens_without_raw_query_field(self):
        group = Group.objects.create(name="operators")
        user = User.objects.create_user(username="audit-user", password="pass")
        user.groups.add(group)

        audit = record_access_audit(
            actor=user,
            request_id="req-audit-1",
            query_hash="sha256:abc",
            returned_chunk_ids=["chunk-1"],
            returned_fact_ids=["fact-1"],
            policy_decision="allowed",
            retrieval_trace={"backend": "test"},
        )

        self.assertEqual(audit.tool_name, "memory.search")
        self.assertEqual(audit.query_hash, "sha256:abc")
        self.assertEqual(audit.returned_chunk_ids, ["chunk-1"])
        self.assertEqual(audit.returned_fact_ids, ["fact-1"])
        self.assertEqual(audit.allowed_scope_tokens, sorted({"org:default", f"user:{user.id}", "role:operators"}))
        self.assertNotIn("query", {field.name for field in MemoryAccessAudit._meta.fields})
        self.assertEqual(str(audit), "req-audit-1:allowed")


class MemoryPrivacyPipelineTests(MemoryModelFactoryMixin, TestCase):
    secret_key = "test-only-pseudonym-secret"

    def test_synthetic_russian_pii_is_redacted_without_real_examples(self):
        from .deidentification import redact_text

        raw_text = (
            "Синтетическая карточка: ФИО: Тестов Тест Тестович; "
            "телефон +7 000 000-00-00; email synthetic.patient@example.test; "
            "СНИЛС 000-000-000 00; паспорт 0000 000000."
        )

        result = redact_text(raw_text)

        self.assertFalse(result.blocked)
        self.assertNotIn("Тестов Тест Тестович", result.safe_text)
        self.assertNotIn("+7 000 000-00-00", result.safe_text)
        self.assertNotIn("synthetic.patient@example.test", result.safe_text)
        self.assertNotIn("000-000-000 00", result.safe_text)
        self.assertNotIn("0000 000000", result.safe_text)
        self.assertIn("[RU_FULL_NAME]", result.safe_text)
        self.assertIn("[PHONE]", result.safe_text)
        self.assertIn("[EMAIL]", result.safe_text)
        self.assertIn("[SNILS]", result.safe_text)
        self.assertIn("[PASSPORT]", result.safe_text)

    def test_pseudonyms_are_stable_with_caller_provided_secret(self):
        from .deidentification import deidentify_text

        raw_text = "ФИО: Тестов Тест Тестович; телефон +7 000 000-00-00."

        first = deidentify_text(raw_text, secret_key=self.secret_key)
        second = deidentify_text(raw_text, secret_key=self.secret_key)
        changed_secret = deidentify_text(raw_text, secret_key="different-test-only-secret")

        self.assertFalse(first.blocked)
        self.assertEqual(first.safe_text, second.safe_text)
        self.assertEqual([item.replacement for item in first.replacements], [item.replacement for item in second.replacements])
        self.assertNotEqual(first.safe_text, changed_secret.safe_text)
        self.assertNotIn("Тестов Тест Тестович", first.safe_text)
        self.assertNotIn("+7 000 000-00-00", first.safe_text)

    def test_secret_material_blocks_deidentification(self):
        from .deidentification import deidentify_text
        from .security import scan_for_secrets

        raw_text = "Техническая заметка: api_key=not-a-real-placeholder-value"

        dlp_result = scan_for_secrets(raw_text)
        deidentified = deidentify_text(raw_text, secret_key=self.secret_key)

        self.assertTrue(dlp_result.blocked)
        self.assertEqual(dlp_result.reason, "credential_material_detected")
        self.assertTrue(deidentified.blocked)
        self.assertEqual(deidentified.reason, "credential_material_detected")
        self.assertEqual(deidentified.safe_text, "")

    def test_snapshot_privacy_pipeline_records_blocked_reason(self):
        snapshot = self.create_snapshot()
        raw_text = "Синтетическая заметка: password=not-a-real-secret-value"

        result = apply_snapshot_privacy_pipeline(snapshot=snapshot, text=raw_text, secret_key=self.secret_key)
        snapshot.refresh_from_db()

        self.assertTrue(result.blocked)
        self.assertEqual(snapshot.status, MemorySnapshot.Status.BLOCKED)
        self.assertEqual(snapshot.blocked_reason, "credential_material_detected")
        self.assertEqual(snapshot.pii_policy_applied, "deidentify_before_index")


class MemoryIndexingPipelineTests(MemoryModelFactoryMixin, TestCase):
    def test_index_snapshot_text_is_idempotent_and_searchable_with_scope_filters(self):
        from .graph_backends import DjangoGraphMemoryBackend
        from .vector_backends import SQLiteFTSMemoryBackend

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            snapshot = self.create_snapshot(
                source_object_id="wo-index-1",
                content_hash="hash-index-1",
                scope_tokens=["org:default", "team:biomed"],
            )
            vector_backend = SQLiteFTSMemoryBackend(Path(tmpdir) / "memory" / "indexes" / "sqlite_fts" / "test.sqlite3")
            graph_backend = DjangoGraphMemoryBackend()
            safe_text = "Сервисная запись alpha indexed: device_alpha -> workorder_beta."

            first = index_ready_snapshot_text(
                snapshot=snapshot,
                safe_text=safe_text,
                vector_backend=vector_backend,
                graph_backend=graph_backend,
                chunk_size=200,
                chunk_overlap=0,
            )
            second = index_ready_snapshot_text(
                snapshot=snapshot,
                safe_text=safe_text,
                vector_backend=vector_backend,
                graph_backend=graph_backend,
                chunk_size=200,
                chunk_overlap=0,
            )

            self.assertEqual(first["chunk_ids"], second["chunk_ids"])
            self.assertEqual(first["fact_ids"], second["fact_ids"])
            self.assertEqual(MemoryChunk.objects.filter(snapshot=snapshot).count(), 1)
            self.assertEqual(MemoryGraphFact.objects.filter(snapshot=snapshot).count(), 1)

            scoped_results = vector_backend.search("indexed", scope_tokens=["team:biomed"], sensitivity="internal")
            denied_results = vector_backend.search("indexed", scope_tokens=["team:finance"], sensitivity="internal")
            graph_results = graph_backend.search_facts("device_alpha", scope_tokens=["team:biomed"])

            self.assertEqual([item.chunk_id for item in scoped_results], first["chunk_ids"])
            self.assertEqual(denied_results, [])
            self.assertEqual([fact.fact_id for fact in graph_results], first["fact_ids"])
            self.assertTrue(Path(snapshot.safe_path).exists())

    def test_memory_search_returns_cited_context_and_audits_without_forbidden_scope(self):
        from .retrieval import memory_search
        from .vector_backends import SQLiteFTSMemoryBackend

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user = User.objects.create_user(username="memory-search-user", password="pass")
            source = self.create_source(code="memory_search_source")
            snapshot = self.create_snapshot(
                source=source,
                source_object_id="safe-doc-1",
                content_hash="hash-search-1",
                scope_tokens=[f"user:{user.id}"],
            )
            vector_backend = SQLiteFTSMemoryBackend(Path(tmpdir) / "memory" / "indexes" / "sqlite_fts" / "search.sqlite3")
            index_ready_snapshot_text(
                snapshot=snapshot,
                safe_text="safe searchable context for pump calibration",
                vector_backend=vector_backend,
                chunk_size=200,
                chunk_overlap=0,
            )

            allowed = memory_search(
                actor=user,
                query="pump calibration",
                scope_tokens=[f"user:{user.id}"],
                sensitivity="internal",
                vector_backend=vector_backend,
                request_id="req-memory-search-1",
            )
            denied = memory_search(
                actor=user,
                query="pump calibration",
                scope_tokens=["team:forbidden"],
                sensitivity="internal",
                vector_backend=vector_backend,
                request_id="req-memory-search-2",
            )

            self.assertEqual(len(allowed["items"]), 1)
            self.assertEqual(len(allowed["citations"]), 1)
            self.assertEqual(allowed["items"][0]["citation_ids"], [allowed["citations"][0]["id"]])
            self.assertIn("safe searchable context", allowed["items"][0]["text"])
            self.assertEqual(denied["items"], [])
            self.assertEqual(denied["citations"], [])
            self.assertEqual(MemoryAccessAudit.objects.filter(request_id="req-memory-search-1", policy_decision="allowed").count(), 1)
            self.assertEqual(MemoryAccessAudit.objects.filter(request_id="req-memory-search-2", policy_decision="allowed").count(), 1)

    def test_memory_search_denies_secret_route(self):
        from django.core.exceptions import PermissionDenied

        from .retrieval import memory_search

        user = User.objects.create_user(username="memory-secret-user", password="pass")

        with self.assertRaises(PermissionDenied):
            memory_search(actor=user, query="secret context", sensitivity="secret", request_id="req-secret-denied")

        self.assertEqual(MemoryAccessAudit.objects.filter(request_id="req-secret-denied", policy_decision="denied").count(), 1)

    def test_reindex_deactivates_stale_chunks_and_facts_without_deleting_snapshot(self):
        from .graph_backends import DjangoGraphMemoryBackend
        from .vector_backends import SQLiteFTSMemoryBackend

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            snapshot = self.create_snapshot(source_object_id="wo-index-2", content_hash="hash-index-2")
            vector_backend = SQLiteFTSMemoryBackend(Path(tmpdir) / "memory" / "indexes" / "sqlite_fts" / "test.sqlite3")
            graph_backend = DjangoGraphMemoryBackend()

            initial = index_ready_snapshot_text(
                snapshot=snapshot,
                safe_text="alpha " * 80 + " device_initial -> workorder_initial",
                vector_backend=vector_backend,
                graph_backend=graph_backend,
                chunk_size=80,
                chunk_overlap=0,
            )
            updated = index_ready_snapshot_text(
                snapshot=snapshot,
                safe_text="short updated text device_updated -> workorder_updated",
                vector_backend=vector_backend,
                graph_backend=graph_backend,
                chunk_size=80,
                chunk_overlap=0,
            )

            self.assertNotEqual(set(initial["chunk_ids"]), set(updated["chunk_ids"]))
            self.assertTrue(MemoryChunk.objects.filter(snapshot=snapshot, chunk_id__in=updated["chunk_ids"], is_active=True).exists())
            self.assertTrue(MemoryChunk.objects.filter(snapshot=snapshot, chunk_id__in=initial["chunk_ids"], is_active=False).exists())
            self.assertTrue(MemoryGraphFact.objects.filter(snapshot=snapshot, fact_id__in=updated["fact_ids"], is_active=True).exists())
            self.assertTrue(MemorySnapshot.objects.filter(pk=snapshot.pk).exists())

            deactivate_snapshot_memory_indexes(snapshot=snapshot)

            self.assertFalse(MemoryChunk.objects.filter(snapshot=snapshot, is_active=True).exists())
            self.assertFalse(MemoryGraphFact.objects.filter(snapshot=snapshot, is_active=True).exists())
            self.assertTrue(MemorySnapshot.objects.filter(pk=snapshot.pk).exists())
