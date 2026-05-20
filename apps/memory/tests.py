from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.apps import apps
from django.core.management import CommandError, call_command, get_commands
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .admin import (
    MemoryAccessAuditAdmin,
    MemoryChunkAdmin,
    MemoryEvalCaseAdmin,
    MemoryGraphFactAdmin,
    MemoryIndexJobAdmin,
    MemoryKnowledgeItemAdmin,
    MemorySnapshotAdmin,
    MemorySourceAdmin,
)
from .models import (
    MemoryAccessAudit,
    MemoryChunk,
    MemoryEvalCase,
    MemoryGraphEntity,
    MemoryGraphExtractionRun,
    MemoryGraphFact,
    MemoryGraphReviewItem,
    MemoryGraphSchemaProposal,
    MemoryIngestionIssue,
    MemoryIngestionRun,
    MemoryIndexJob,
    MemoryKnowledgeCandidate,
    MemoryKnowledgeEvent,
    MemoryKnowledgeItem,
    MemoryReflectionRun,
    MemorySnapshot,
    MemorySource,
    MemorySourceObject,
    MemoryWriteRequest,
    SecretAccessAudit,
    SecretHandle,
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


MEMORY_INGESTION_BOOTSTRAP_MODELS = {
    "MemorySourceObject": {
        "source",
        "object_id",
        "object_uri",
        "relative_path",
        "file_name",
        "extension",
        "mime_type",
        "size_bytes",
        "mtime",
        "content_hash",
        "etag_or_inode",
        "last_seen_at",
        "last_stable_at",
        "discovery_status",
        "ingestion_status",
        "last_ingested_at",
        "failure_count",
        "last_error",
        "partial_reason",
        "acl_fingerprint",
        "metadata",
    },
    "MemoryIngestionRun": {
        "source",
        "status",
        "started_at",
        "finished_at",
        "dry_run",
        "metrics",
        "error_message",
    },
    "MemoryIngestionIssue": {
        "source",
        "source_object",
        "run",
        "issue_kind",
        "status",
        "severity",
        "message",
        "metadata",
    },
    "MemoryGraphSchemaProposal": {
        "proposal_kind",
        "status",
        "payload",
        "evidence",
        "confidence",
        "reviewed_by",
    },
    "MemoryGraphEntity": {
        "entity_id",
        "entity_type",
        "canonical_name",
        "aliases",
        "attributes",
        "scope_tokens",
        "sensitivity",
        "is_active",
    },
    "MemoryGraphExtractionRun": {
        "source",
        "snapshot",
        "status",
        "started_at",
        "finished_at",
        "metrics",
        "error_message",
    },
    "MemoryGraphReviewItem": {
        "item_kind",
        "status",
        "payload",
        "evidence",
        "decision",
        "reviewed_by",
    },
}


def get_optional_memory_model(model_name):
    try:
        return apps.get_model("memory", model_name)
    except LookupError:
        return None


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
            MemorySourceObject: django_admin.site._registry[MemorySourceObject].__class__,
            MemoryIngestionRun: django_admin.site._registry[MemoryIngestionRun].__class__,
            MemoryIngestionIssue: django_admin.site._registry[MemoryIngestionIssue].__class__,
            MemoryGraphEntity: django_admin.site._registry[MemoryGraphEntity].__class__,
            MemoryGraphExtractionRun: django_admin.site._registry[MemoryGraphExtractionRun].__class__,
            MemoryGraphSchemaProposal: django_admin.site._registry[MemoryGraphSchemaProposal].__class__,
            MemoryGraphReviewItem: django_admin.site._registry[MemoryGraphReviewItem].__class__,
            MemoryWriteRequest: django_admin.site._registry[MemoryWriteRequest].__class__,
            MemoryKnowledgeItem: MemoryKnowledgeItemAdmin,
            MemoryKnowledgeEvent: django_admin.site._registry[MemoryKnowledgeEvent].__class__,
            MemoryKnowledgeCandidate: django_admin.site._registry[MemoryKnowledgeCandidate].__class__,
            MemoryReflectionRun: django_admin.site._registry[MemoryReflectionRun].__class__,
            SecretHandle: django_admin.site._registry[SecretHandle].__class__,
            SecretAccessAudit: django_admin.site._registry[SecretAccessAudit].__class__,
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
            MemorySourceObject,
            MemoryIngestionRun,
            MemoryIngestionIssue,
            MemoryGraphEntity,
            MemoryGraphExtractionRun,
            MemoryGraphSchemaProposal,
            MemoryGraphReviewItem,
            MemoryWriteRequest,
            MemoryKnowledgeItem,
            MemoryKnowledgeEvent,
            MemoryKnowledgeCandidate,
            MemoryReflectionRun,
            SecretHandle,
            SecretAccessAudit,
        ):
            with self.subTest(model=model.__name__):
                model_admin = django_admin.site._registry[model]
                self.assertTrue(path_fields.isdisjoint(model_admin.search_fields))


class MemoryIngestionBootstrapExpectationTests(MemoryModelFactoryMixin, TestCase):
    def test_bootstrap_models_expose_expected_fields_when_available(self):
        available_models = []

        for model_name, expected_fields in MEMORY_INGESTION_BOOTSTRAP_MODELS.items():
            model = get_optional_memory_model(model_name)
            if model is None:
                continue
            available_models.append(model_name)
            with self.subTest(model=model_name):
                field_names = {field.name for field in model._meta.get_fields()}
                self.assertTrue(
                    expected_fields.issubset(field_names),
                    f"{model_name} is missing fields: {sorted(expected_fields - field_names)}",
                )

        if not available_models:
            self.skipTest("memory ingestion/bootstrap models are not implemented yet")

    def test_bootstrap_models_are_registered_in_admin_when_available(self):
        available_models = []

        for model_name in MEMORY_INGESTION_BOOTSTRAP_MODELS:
            model = get_optional_memory_model(model_name)
            if model is None:
                continue
            available_models.append(model_name)
            with self.subTest(model=model_name):
                self.assertIn(model, django_admin.site._registry)
                self.assertEqual(
                    django_admin.site._registry[model].__class__.__name__,
                    f"{model_name}Admin",
                )

        if not available_models:
            self.skipTest("memory ingestion/bootstrap admin registrations are not implemented yet")

    def test_discovery_and_ingestion_commands_accept_dry_run_when_available(self):
        command_cases = (
            ("memory_discover_source", ["--source-code", "bootstrap_test_source", "--dry-run"]),
            ("memory_ingest_source", ["--source-code", "bootstrap_test_source", "--dry-run"]),
            ("memory_graph_extract", ["--source-code", "bootstrap_test_source", "--dry-run"]),
        )
        available_commands = get_commands()
        checked_commands = []

        self.create_source(code="bootstrap_test_source", source_kind="documentation", index_profiles=["graph_default"])

        for command_name, args in command_cases:
            if command_name not in available_commands:
                continue
            checked_commands.append(command_name)
            with self.subTest(command=command_name):
                try:
                    call_command(command_name, *args, verbosity=0)
                except CommandError as exc:
                    self.fail(f"{command_name} --dry-run should not fail for a known source: {exc}")

        if not checked_commands:
            self.skipTest("memory discovery/ingestion commands are not implemented yet")


class MemoryDocumentIngestionPipelineTests(MemoryModelFactoryMixin, TestCase):
    def test_discover_source_objects_creates_durable_file_state(self):
        from .document_ingestion import discover_source_objects

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "memory_docs"
            root.mkdir()
            (root / "procedure.txt").write_text("Procedure calibration device_alpha -> procedure_beta", encoding="utf-8")
            source = self.create_source(
                code="local_docs_discovery",
                source_kind="local_path",
                domain="docs",
                scope_rule="authenticated_user",
                config={
                    "source_ref": str(root),
                    "ignore_patterns": [],
                    "ingestion_profile": "corporate_docs_windows_v1",
                },
            )

            metrics = discover_source_objects(source=source, dry_run=False)

            self.assertEqual(metrics["seen"], 1)
            source_object = MemorySourceObject.objects.get(source=source)
            self.assertEqual(source_object.relative_path, "procedure.txt")
            self.assertEqual(source_object.extension, ".txt")
            self.assertEqual(source_object.ingestion_status, MemorySourceObject.IngestionStatus.PENDING)
            self.assertTrue(source_object.content_hash)

    def test_ingest_source_objects_writes_safe_snapshot_chunks_and_graph_fact(self):
        from .document_ingestion import discover_source_objects, ingest_source_objects

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            root = Path(tmpdir) / "memory_docs"
            root.mkdir()
            (root / "procedure.txt").write_text("Procedure calibration device_alpha -> procedure_beta", encoding="utf-8")
            source = self.create_source(
                code="local_docs_ingestion",
                source_kind="local_path",
                domain="docs",
                scope_rule="authenticated_user",
                config={
                    "source_ref": str(root),
                    "ignore_patterns": [],
                    "ingestion_profile": "corporate_docs_windows_v1",
                },
            )

            with self.settings(DATA_DIR=data_dir):
                discover_source_objects(source=source, dry_run=False)
                metrics = ingest_source_objects(source=source, dry_run=False)

            source_object = MemorySourceObject.objects.get(source=source)
            self.assertEqual(metrics["ingested"], 1)
            self.assertEqual(source_object.ingestion_status, MemorySourceObject.IngestionStatus.INGESTED)
            self.assertEqual(MemorySnapshot.objects.filter(source=source, status=MemorySnapshot.Status.READY).count(), 1)
            self.assertEqual(MemoryChunk.objects.filter(source_code=source.code, is_active=True).count(), 1)
            self.assertEqual(MemoryGraphFact.objects.filter(snapshot__source=source, is_active=True).count(), 1)

    def test_ingest_source_objects_creates_issue_for_unsupported_binary(self):
        from .document_ingestion import discover_source_objects, ingest_source_objects

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "memory_docs"
            root.mkdir()
            (root / "archive.bin").write_bytes(b"\x00\x01unsupported")
            source = self.create_source(
                code="local_docs_issue",
                source_kind="local_path",
                domain="docs",
                scope_rule="authenticated_user",
                config={
                    "source_ref": str(root),
                    "ignore_patterns": [],
                    "ingestion_profile": "corporate_docs_windows_v1",
                },
            )

            discover_source_objects(source=source, dry_run=False)
            metrics = ingest_source_objects(source=source, dry_run=False)

            self.assertEqual(metrics["issues"], 1)
            issue = MemoryIngestionIssue.objects.get(source=source)
            self.assertEqual(issue.issue_kind, MemoryIngestionIssue.IssueKind.UNSUPPORTED_FORMAT)
            self.assertEqual(issue.status, MemoryIngestionIssue.Status.OPEN)


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

    def test_secret_scanner_detects_russian_password_assignment(self):
        from .security import scan_for_secrets

        result = scan_for_secrets("Запомни пароль: E2E-Secret-Value-987!")

        self.assertTrue(result.blocked)
        self.assertEqual(result.findings[0].finding_type, "credential_assignment")


class MemoryChatKnowledgeTests(TestCase):
    def create_chat(self, *, username="chat-memory-user", text="Запомни: насос alpha требует калибровку."):
        from apps.ai.models import ChatMessage, ChatSession

        user = User.objects.create_user(username=username, password="pass")
        session = ChatSession.objects.create(user=user, title="Memory chat")
        message = ChatMessage.objects.create(session=session, role=ChatMessage.Role.USER, content=text)
        return user, session, message

    def test_remember_request_queues_personal_memory_by_default(self):
        from .chat_memory import process_memory_write_request, queue_memory_remember

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user, session, message = self.create_chat()
            result = queue_memory_remember(
                actor=user,
                session=session,
                payload={"message_ids": [message.id], "user_note": "важно"},
                request_id="req-remember-1",
            )
            request = MemoryWriteRequest.objects.get(request_id=result["request_id"])

            self.assertEqual(request.target_scope, MemoryWriteRequest.TargetScope.PERSONAL)
            self.assertEqual(request.status, MemoryWriteRequest.Status.QUEUED)

            processed = process_memory_write_request(request)
            request.refresh_from_db()

            self.assertEqual(request.status, MemoryWriteRequest.Status.ACCEPTED)
            self.assertTrue(MemoryKnowledgeItem.objects.filter(owner_user=user, scope=MemoryKnowledgeItem.Scope.PERSONAL).exists())
            self.assertTrue((Path(tmpdir) / "memory" / "chat_knowledge" / "users" / str(user.id) / "memory.current.json").exists())
            self.assertIn("memory_id", processed)

    def test_secret_span_becomes_handle_and_non_secret_text_is_indexed(self):
        from .chat_memory import process_memory_write_request, queue_memory_remember

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir), LOCAL_BUSINESS_SECRET_VAULT_BASE_URL="https://vault.example"):
            user, session, message = self.create_chat(
                text="Запомни: тестовый стенд называется alpha. Пароль: not-a-real-secret-value"
            )
            queued = queue_memory_remember(
                actor=user,
                session=session,
                payload={"message_ids": [message.id]},
                request_id="req-secret-memory",
            )
            request = MemoryWriteRequest.objects.get(request_id=queued["request_id"])

            process_memory_write_request(request)
            item = MemoryKnowledgeItem.objects.get(owner_user=user)

            self.assertIn("тестовый стенд называется alpha", item.text)
            self.assertIn("<SECRET_HANDLE:secret:", item.text)
            self.assertNotIn("not-a-real-secret-value", item.text)
            self.assertEqual(SecretHandle.objects.count(), 1)
            self.assertEqual(SecretAccessAudit.objects.count(), 1)

    def test_organization_memory_requires_staff_permission(self):
        from django.core.exceptions import PermissionDenied

        from .chat_memory import queue_memory_remember

        user, session, message = self.create_chat(username="org-denied-user")

        with self.assertRaises(PermissionDenied):
            queue_memory_remember(
                actor=user,
                session=session,
                payload={"message_ids": [message.id], "target_scope": "organization"},
                request_id="req-org-denied",
            )

    def test_reflection_creates_organization_candidate_for_high_importance_personal_memory(self):
        from .chat_memory import process_memory_write_request, propose_reflection_candidates, queue_memory_remember

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user, session, message = self.create_chat(text="Запомни: общий регламент alpha действует для отдела.")
            queued = queue_memory_remember(
                actor=user,
                session=session,
                payload={"message_ids": [message.id], "importance": "organization_candidate"},
                request_id="req-candidate",
            )
            process_memory_write_request(MemoryWriteRequest.objects.get(request_id=queued["request_id"]))

            candidates = propose_reflection_candidates()

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].status, MemoryKnowledgeCandidate.Status.PROPOSED)

    def test_owner_can_edit_and_delete_personal_memory(self):
        from .chat_memory import delete_personal_memory, edit_personal_memory, process_memory_write_request, queue_memory_remember

        with TemporaryDirectory() as tmpdir, self.settings(DATA_DIR=Path(tmpdir)):
            user, session, message = self.create_chat()
            queued = queue_memory_remember(actor=user, session=session, payload={"message_ids": [message.id]})
            process_memory_write_request(MemoryWriteRequest.objects.get(request_id=queued["request_id"]))
            item = MemoryKnowledgeItem.objects.get(owner_user=user)

            edited = edit_personal_memory(actor=user, memory_id=item.memory_id, new_text="Насос alpha калибруется ежемесячно.")
            item.refresh_from_db()
            self.assertEqual(edited["status"], MemoryKnowledgeItem.Status.ACTIVE)
            self.assertIn("ежемесячно", item.text)

            deleted = delete_personal_memory(actor=user, memory_id=item.memory_id)
            item.refresh_from_db()
            self.assertEqual(deleted["status"], MemoryKnowledgeItem.Status.DELETED)
            self.assertEqual(item.status, MemoryKnowledgeItem.Status.DELETED)


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
