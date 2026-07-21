"""Тесты external API connector landing zone и очереди."""
from apps.memory.tests._common import *  # noqa: F401,F403


class MemoryExternalConnectorTests(TestCase):
    databases = RUNTIME_DATABASES
    def create_external_source(self):
        return MemorySource.objects.create(
            code="external_api_landing_zone_test",
            title="External API landing zone test",
            source_kind="external_api_snapshot",
            domain="external_systems",
            owner="knowledge_owner",
            sync_mode="scheduled",
            scope_rule="manual_scope_mapping",
            sensitivity="internal",
            pii_policy="deidentify_before_index",
            extractor_profile="external_api_object_v1",
            chunking_profile="external_api_object_v1",
            index_profiles=["fulltext_default"],
            config={
                "external_connector": {
                    "queue_backend": "sqlite",
                    "raw_mode": "short_lived_raw_quarantine",
                    "scope_mapping": "manual",
                    "retention": {
                        "raw_quarantine_days": 14,
                        "normalized_envelope_days": 90,
                        "manifest_days": 365,
                        "tombstone_days": 1095,
                    },
                }
            },
        )

    def test_external_envelope_queue_handoff_indexes_memory(self):
        from ..external_connectors import (
            build_external_envelope,
            enqueue_external_envelope,
            get_external_queue_backend,
            process_external_connector_jobs,
        )

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with self.settings(
                DATA_DIR=data_dir,
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND="sqlite",
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=data_dir / "queues" / "external.sqlite3",
            ):
                source = self.create_external_source()
                envelope = build_external_envelope(
                    source_code=source.code,
                    collection="tickets",
                    object_type="ticket",
                    external_id="T-100",
                    title="Плановая проверка насоса",
                    payload={"status": "open", "department": "ОИТ", "summary": "Насос alpha требует проверки."},
                    run_id="run-001",
                    scope_tokens=["org:default"],
                )

                job = enqueue_external_envelope(
                    source=source,
                    envelope=envelope,
                    raw_response={"id": "T-100", "status": "open"},
                    request_id="req-external-1",
                )
                duplicate_job = enqueue_external_envelope(source=source, envelope=envelope, request_id="req-external-1")

                self.assertEqual(job.job_id, duplicate_job.job_id)
                self.assertEqual(get_external_queue_backend().stats(), {"pending": 1})
                self.assertTrue(
                    (
                        data_dir
                        / "memory"
                        / "external_api"
                        / source.code
                        / "run-001"
                        / "raw_quarantine"
                        / "ticket"
                        / "T-100.json"
                    ).exists()
                )

                results = process_external_connector_jobs(limit=5)

                self.assertEqual(results[0]["status"], "succeeded")
                document = MemorySearchDocument.objects.get(source_object__source=source, index_status=MemorySearchDocument.IndexStatus.READY)
                self.assertEqual((document.source_object.metadata or {}).get("scope_tokens"), ["org:default"])
                self.assertEqual(document.metadata["external"]["external_id"], "T-100")
                self.assertEqual(get_external_queue_backend().stats(), {"succeeded": 1})

                manifest = json.loads(
                    (
                        data_dir
                        / "memory"
                        / "external_api"
                        / source.code
                        / "run-001"
                        / "manifest.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(manifest["schema_version"], "external-memory-manifest-v1")
                self.assertEqual(manifest["connector_version"], "external-api-mvp-v1")
                self.assertTrue(manifest["started_at"])
                self.assertTrue(manifest["finished_at"])
                self.assertEqual(manifest["object_count"], 1)
                self.assertEqual(manifest["error_count"], 0)
                self.assertEqual(manifest["cursor_state"], {})
                self.assertEqual(manifest["retention_class"], "external_default")
                self.assertIn("objects", manifest)

    def test_database_external_queue_backend_leases_and_completes_jobs(self):
        from ..external_connectors import ExternalJobKind, ExternalJobStatus, get_external_queue_backend

        with self.settings(LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND="database"):
            backend = get_external_queue_backend()
            job = backend.enqueue(
                source_code="external_api_landing_zone_test",
                job_kind=ExternalJobKind.HANDOFF_EXTERNAL_OBJECT_TO_MEMORY,
                payload={"envelope_path": "/tmp/envelope.json"},
                idempotency_key="external-api-test:1",
                request_id="req-db-queue-1",
            )
            duplicate = backend.enqueue(
                source_code="external_api_landing_zone_test",
                job_kind=ExternalJobKind.HANDOFF_EXTERNAL_OBJECT_TO_MEMORY,
                payload={"envelope_path": "/tmp/envelope.json"},
                idempotency_key="external-api-test:1",
                request_id="req-db-queue-1",
            )

            self.assertEqual(job.job_id, duplicate.job_id)
            self.assertEqual(backend.stats(), {ExternalJobStatus.PENDING: 1})

            leased = backend.lease(limit=1, lease_seconds=60)
            self.assertEqual([item.job_id for item in leased], [job.job_id])
            self.assertEqual(leased[0].attempt_count, 1)
            self.assertEqual(backend.stats(), {ExternalJobStatus.RUNNING: 1})

            completed = backend.complete(job.job_id, result={"ok": True})

            self.assertEqual(completed.status, ExternalJobStatus.SUCCEEDED)
            self.assertEqual(backend.stats(), {ExternalJobStatus.SUCCEEDED: 1})

    def test_external_envelope_blocks_secret_before_queue(self):
        from django.core.exceptions import ValidationError

        from ..external_connectors import build_external_envelope, enqueue_external_envelope

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with self.settings(
                DATA_DIR=data_dir,
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND="sqlite",
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=data_dir / "queues" / "external.sqlite3",
            ):
                source = self.create_external_source()
                envelope = build_external_envelope(
                    source_code=source.code,
                    collection="tickets",
                    object_type="ticket",
                    external_id="T-101",
                    title="Unsafe record",
                    payload={"note": "password=not-a-real-secret-value"},
                    run_id="run-secret",
                )

                with self.assertRaises(ValidationError):
                    enqueue_external_envelope(source=source, envelope=envelope)

                self.assertEqual(MemorySearchDocument.objects.count(), 0)

    def test_external_raw_secret_skips_quarantine_and_records_issue(self):
        from ..external_connectors import build_external_envelope, enqueue_external_envelope

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with self.settings(
                DATA_DIR=data_dir,
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND="sqlite",
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=data_dir / "queues" / "external.sqlite3",
            ):
                source = self.create_external_source()
                envelope = build_external_envelope(
                    source_code=source.code,
                    collection="tickets",
                    object_type="ticket",
                    external_id="T-101-RAW",
                    title="Raw unsafe record",
                    payload={"summary": "safe normalized text"},
                    run_id="run-raw-secret",
                )

                enqueue_external_envelope(
                    source=source,
                    envelope=envelope,
                    raw_response={"id": "T-101-RAW", "password": "not-a-real-secret-value"},
                )

                run_dir = data_dir / "memory" / "external_api" / source.code / "run-raw-secret"
                self.assertFalse((run_dir / "raw_quarantine" / "ticket" / "T-101-RAW.json").exists())
                issues_path = run_dir / "issues.jsonl"
                self.assertTrue(issues_path.exists())
                issue = json.loads(issues_path.read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(issue["issue_kind"], "raw_quarantine_secret_detected")
                manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["error_count"], 1)
                self.assertEqual(manifest["issues_path"], str(issues_path))

    def test_external_envelope_rejects_invalid_content_hash(self):
        from django.core.exceptions import ValidationError

        from ..external_connectors import build_external_envelope, enqueue_external_envelope

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with self.settings(
                DATA_DIR=data_dir,
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND="sqlite",
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=data_dir / "queues" / "external.sqlite3",
            ):
                source = self.create_external_source()
                envelope = build_external_envelope(
                    source_code=source.code,
                    collection="tickets",
                    object_type="ticket",
                    external_id="T-BAD-HASH",
                    title="Bad hash",
                    payload={"summary": "safe"},
                    run_id="run-bad-hash",
                )
                envelope["payload"]["summary"] = "tampered"

                with self.assertRaises(ValidationError):
                    enqueue_external_envelope(source=source, envelope=envelope)

    def test_external_delete_envelope_deactivates_search_document(self):
        from ..external_connectors import (
            build_external_envelope,
            enqueue_external_envelope,
            latest_external_tombstone,
            process_external_connector_jobs,
        )

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with self.settings(
                DATA_DIR=data_dir,
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND="sqlite",
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=data_dir / "queues" / "external.sqlite3",
            ):
                source = self.create_external_source()
                upsert = build_external_envelope(
                    source_code=source.code,
                    collection="tickets",
                    object_type="ticket",
                    external_id="T-102",
                    title="Temporary record",
                    payload={"summary": "temporary"},
                    run_id="run-delete",
                    source_updated_at="2026-01-01T00:00:00Z",
                )
                enqueue_external_envelope(source=source, envelope=upsert)
                process_external_connector_jobs(limit=5)
                self.assertEqual(
                    MemorySearchDocument.objects.filter(source_object__source=source, index_status=MemorySearchDocument.IndexStatus.READY).count(),
                    1,
                )

                delete = build_external_envelope(
                    source_code=source.code,
                    collection="tickets",
                    object_type="ticket",
                    external_id="T-102",
                    title="Temporary record",
                    payload={},
                    operation="delete",
                    run_id="run-delete",
                    source_updated_at="2026-01-02T00:00:00Z",
                )
                enqueue_external_envelope(source=source, envelope=delete)
                process_external_connector_jobs(limit=5)

                self.assertEqual(
                    MemorySearchDocument.objects.filter(source_object__source=source, index_status=MemorySearchDocument.IndexStatus.READY).count(),
                    0,
                )
                tombstone = latest_external_tombstone(source=source, envelope=delete)
                self.assertIsNotNone(tombstone)
                self.assertEqual(tombstone["external_id"], "T-102")

    def test_external_stale_upsert_after_tombstone_is_rejected(self):
        from django.core.exceptions import ValidationError

        from ..external_connectors import build_external_envelope, enqueue_external_envelope, process_external_connector_jobs

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with self.settings(
                DATA_DIR=data_dir,
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND="sqlite",
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=data_dir / "queues" / "external.sqlite3",
            ):
                source = self.create_external_source()
                delete = build_external_envelope(
                    source_code=source.code,
                    collection="tickets",
                    object_type="ticket",
                    external_id="T-STALE",
                    title="Deleted record",
                    payload={},
                    operation="delete",
                    run_id="run-stale",
                    source_updated_at="2026-01-02T00:00:00Z",
                )
                enqueue_external_envelope(source=source, envelope=delete)
                process_external_connector_jobs(limit=5)

                stale = build_external_envelope(
                    source_code=source.code,
                    collection="tickets",
                    object_type="ticket",
                    external_id="T-STALE",
                    title="Deleted record",
                    payload={"summary": "old version"},
                    run_id="run-stale",
                    source_updated_at="2026-01-01T00:00:00Z",
                )
                with self.assertRaises(ValidationError):
                    enqueue_external_envelope(source=source, envelope=stale)

    def test_external_cleanup_command_dry_run_and_delete_modes(self):
        from ..external_connectors import build_external_envelope, enqueue_external_envelope

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with self.settings(
                DATA_DIR=data_dir,
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND="sqlite",
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=data_dir / "queues" / "external.sqlite3",
            ):
                source = self.create_external_source()
                envelope = build_external_envelope(
                    source_code=source.code,
                    collection="tickets",
                    object_type="ticket",
                    external_id="T-CLEAN",
                    title="Cleanup",
                    payload={"summary": "cleanup object"},
                    run_id="run-cleanup",
                )
                enqueue_external_envelope(source=source, envelope=envelope, raw_response={"id": "T-CLEAN"})

                run_dir = data_dir / "memory" / "external_api" / source.code / "run-cleanup"
                object_path = run_dir / "objects" / "ticket" / "T-CLEAN.json"
                raw_path = run_dir / "raw_quarantine" / "ticket" / "T-CLEAN.json"
                manifest_path = run_dir / "manifest.json"
                old_timestamp = timezone.datetime(2020, 1, 1, tzinfo=timezone.get_current_timezone()).timestamp()
                for path in (object_path, raw_path, manifest_path):
                    os.utime(path, (old_timestamp, old_timestamp))

                call_command("memory_external_cleanup", "--source-code", source.code, "--dry-run", verbosity=0)
                self.assertTrue(object_path.exists())
                self.assertTrue(raw_path.exists())
                self.assertTrue(manifest_path.exists())

                call_command("memory_external_cleanup", "--source-code", source.code, "--yes", verbosity=0)
                self.assertFalse(object_path.exists())
                self.assertFalse(raw_path.exists())
                self.assertFalse(manifest_path.exists())

    def test_external_queue_status_details_shows_dead_letter_error(self):
        from ..external_connectors import ExternalJobKind, get_external_queue_backend, process_external_connector_jobs

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with self.settings(
                DATA_DIR=data_dir,
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND="sqlite",
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=data_dir / "queues" / "external.sqlite3",
            ):
                source = self.create_external_source()
                backend = get_external_queue_backend()
                backend.enqueue(
                    source_code=source.code,
                    job_kind=ExternalJobKind.DISCOVER_EXTERNAL_SOURCE,
                    payload={},
                    idempotency_key="unsupported-job",
                    max_attempts=1,
                )
                process_external_connector_jobs(limit=5)

                out = StringIO()
                call_command("memory_external_queue_status", "--details", "--limit", "5", stdout=out, verbosity=0)
                output = out.getvalue()
                self.assertIn("dead_letter", output)
                self.assertIn("Unsupported external connector job kind", output)

    def test_external_connector_management_commands_smoke(self):
        from apps.core.json_utils import atomic_write_json

        from ..external_connectors import build_external_envelope

        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with self.settings(
                DATA_DIR=data_dir,
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND="sqlite",
                LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=data_dir / "queues" / "external.sqlite3",
            ):
                source = self.create_external_source()
                envelope = build_external_envelope(
                    source_code=source.code,
                    collection="tickets",
                    object_type="ticket",
                    external_id="T-103",
                    title="Command smoke",
                    payload={"summary": "command smoke object"},
                    run_id="run-command",
                )
                envelope_path = data_dir / "input" / "envelope.json"
                envelope_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(envelope_path, envelope)

                call_command(
                    "memory_external_enqueue",
                    "--source-code",
                    source.code,
                    "--envelope-file",
                    str(envelope_path),
                    verbosity=0,
                )
                call_command("memory_external_queue_status", verbosity=0)
                call_command("memory_external_worker", "--limit", "5", verbosity=0)

                self.assertEqual(
                    MemorySearchDocument.objects.filter(source_object__source=source, index_status=MemorySearchDocument.IndexStatus.READY).count(),
                    1,
                )
