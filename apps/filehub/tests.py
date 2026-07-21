import os
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.memory.document_ingestion import sha256_file
from apps.memory.models import MemoryIngestionIssue, MemorySourceObject
from apps.memory.tests import MemoryModelFactoryMixin

from .file_organization import ensure_file_object_for_source_object
from .file_organization_baseline import build_baseline_virtual_structure
from .file_organization_incoming import process_incoming_folder
from .file_organization_move import create_move_job_for_file, purge_ready_source_files, run_move_worker
from .file_organization_stats import build_organization_proposals, record_file_usage_event
from .models import (
    MemoryFileMoveJob,
    MemoryFileObject,
    MemoryFileObjectVersion,
    MemoryFileOrganizationDecision,
    MemoryFileOrganizationProposal,
    MemoryFilePathAlias,
    MemoryFilePhysicalPlacement,
    MemoryFileUsageEvent,
    MemoryFileVirtualPlacement,
    MemoryFileVirtualRule,
    MemoryFileVirtualView,
)

User = get_user_model()
RUNTIME_DATABASES = {"default"}


def _file_organization_profiles(*, source_code, managed_root, enabled=True, retention_days=30, min_users=2, min_events=2, min_files=1, min_confidence=0.2):
    return {
        "version": "1.0",
        "name": "memory_file_organization_profiles",
        "description": "Test file organization profiles.",
        "profiles": {
            "test_file_auto_org_v1": {
                "enabled": enabled,
                "source_code": source_code,
                "incoming_path": "incoming/new",
                "managed_root": str(managed_root),
                "baseline_profile": "baseline_auto_v1",
                "physical_move_policy": "approval_required",
                "source_delete_policy": {
                    "mode": "quarantine_then_purge",
                    "retention_days": retention_days,
                    "requires_backup_checkpoint": True,
                },
                "storage_backend": "managed_fs",
                "future_backends": ["s3_compatible"],
                "proposal_thresholds": {
                    "min_users": min_users,
                    "min_events": min_events,
                    "min_files": min_files,
                    "min_confidence": min_confidence,
                },
            }
        },
    }


class MemoryFileAutoOrganizationTests(MemoryModelFactoryMixin, TestCase):
    databases = RUNTIME_DATABASES

    def create_file_source(self, *, code="file_auto_org_source", root=None, group_name="docs-readers"):
        Group.objects.get_or_create(name=group_name)
        return self.create_source(
            code=code,
            source_kind="local_path",
            domain="docs",
            scope_rule="authenticated_user",
            config={
                "source_ref": str(root or "/tmp/not-used"),
                "ignore_patterns": [],
                "ingestion_profile": "corporate_docs_windows_v1",
                "file_organization_profile": "test_file_auto_org_v1",
                "default_acl": {"allow": [{"kind": "group", "name": group_name}]},
            },
        )

    def create_source_object(self, *, source, relative_path, content_hash="hash-1", size_bytes=10, object_uri=None):
        return MemorySourceObject.objects.create(
            source=source,
            object_id=f"object:{relative_path}",
            object_uri=object_uri or f"/tmp/{relative_path}",
            relative_path=relative_path,
            file_name=Path(relative_path).name,
            extension=Path(relative_path).suffix.lower(),
            mime_type="text/plain",
            size_bytes=size_bytes,
            mtime=timezone.now(),
            content_hash=content_hash,
            metadata={"scope_tokens": ["org:default"]},
        )

    def test_stable_file_identity_survives_relative_path_change_and_keeps_path_history(self):
        source = self.create_file_source()
        first = self.create_source_object(source=source, relative_path="old/dogovor-2026.txt", content_hash="same-hash", size_bytes=42)
        second = self.create_source_object(source=source, relative_path="new/dogovor-2026.txt", content_hash="same-hash", size_bytes=42)

        first_file = ensure_file_object_for_source_object(first)
        second_file = ensure_file_object_for_source_object(second)

        self.assertEqual(first_file.file_id, second_file.file_id)
        self.assertEqual(MemoryFileObject.objects.count(), 1)
        self.assertEqual(MemoryFileObjectVersion.objects.count(), 1)
        aliases = set(MemoryFilePathAlias.objects.values_list("relative_path", flat=True))
        self.assertEqual(aliases, {"old/dogovor-2026.txt", "new/dogovor-2026.txt"})
        self.assertEqual(MemoryFilePhysicalPlacement.objects.filter(file_object=first_file).count(), 2)

    def test_baseline_creates_virtual_structure_without_physical_changes_and_routes_review(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "source"
            managed = Path(tmpdir) / "managed"
            root.mkdir()
            managed.mkdir()
            source_file = root / "unknown.bin"
            source_file.write_bytes(b"opaque")
            source = self.create_file_source(code="file_baseline_review", root=root)
            source_object = self.create_source_object(
                source=source,
                relative_path="unknown.bin",
                content_hash="",
                size_bytes=source_file.stat().st_size,
                object_uri=str(source_file),
            )

            profiles = _file_organization_profiles(source_code=source.code, managed_root=managed)
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                metrics = build_baseline_virtual_structure(source=source, dry_run=False)

            self.assertTrue(source_file.exists())
            self.assertEqual(metrics["placements"], 1)
            placement = MemoryFileVirtualPlacement.objects.get(file_object__source=source)
            self.assertTrue(placement.review_required)
            self.assertIn("content_hash_missing", placement.conflicts)
            issue = MemoryIngestionIssue.objects.get(source=source, source_object=source_object)
            self.assertEqual(issue.issue_kind, MemoryIngestionIssue.IssueKind.CANONICALIZATION_CONFLICT)

    def test_incoming_worker_blocks_secret_file_and_does_not_publish_virtual_placement(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "source"
            managed = Path(tmpdir) / "managed"
            incoming = root / "incoming" / "new"
            incoming.mkdir(parents=True)
            managed.mkdir()
            secret_file = incoming / "secret.txt"
            secret_file.write_text("api_key = sk-test-secret-value-123456789", encoding="utf-8")
            old_timestamp = timezone.now().timestamp() - 60
            os.utime(secret_file, (old_timestamp, old_timestamp))
            source = self.create_file_source(code="file_incoming_secret", root=root)
            profiles = _file_organization_profiles(source_code=source.code, managed_root=managed)

            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                metrics = process_incoming_folder(source=source, dry_run=False)

            self.assertEqual(metrics["blocked"], 1)
            source_object = MemorySourceObject.objects.get(source=source, file_name="secret.txt")
            self.assertEqual(source_object.ingestion_status, MemorySourceObject.IngestionStatus.FAILED)
            self.assertFalse(MemoryFileVirtualPlacement.objects.filter(file_object__source=source).exists())
            issue = MemoryIngestionIssue.objects.get(source=source, source_object=source_object)
            self.assertEqual(issue.issue_kind, MemoryIngestionIssue.IssueKind.SECRET_BLOCKED)

    def test_structure_stats_respects_aggregation_threshold_before_creating_proposal(self):
        with TemporaryDirectory() as tmpdir:
            managed = Path(tmpdir) / "managed"
            managed.mkdir()
            source = self.create_file_source(code="file_stats_threshold")
            source_object = self.create_source_object(source=source, relative_path="contracts/dogovor-2026.txt")
            file_object = ensure_file_object_for_source_object(source_object)
            view = MemoryFileVirtualView.objects.create(
                source=source,
                view_kind=MemoryFileVirtualView.ViewKind.USER,
                slug="user-view-1",
                title="User view",
                status=MemoryFileVirtualView.Status.ACTIVE,
            )
            placement = MemoryFileVirtualPlacement.objects.create(
                view=view,
                file_object=file_object,
                virtual_path="Договоры/2026/dogovor-2026.txt",
                placement_source=MemoryFileVirtualPlacement.PlacementSource.USER_MANUAL,
                confidence="0.9000",
                status=MemoryFileVirtualPlacement.Status.ACCEPTED,
            )
            user_one = User.objects.create_user(username="stats-user-one", password="pass")
            user_two = User.objects.create_user(username="stats-user-two", password="pass")
            profiles = _file_organization_profiles(source_code=source.code, managed_root=managed, min_users=2, min_events=2)

            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                record_file_usage_event(
                    source=source,
                    event_kind=MemoryFileUsageEvent.EventKind.BASELINE_ACCEPTED,
                    file_object=file_object,
                    view=view,
                    actor=user_one,
                    virtual_path=placement.virtual_path,
                )
                first_metrics = build_organization_proposals(source=source, dry_run=False)
                record_file_usage_event(
                    source=source,
                    event_kind=MemoryFileUsageEvent.EventKind.VIRTUAL_MOVE,
                    file_object=file_object,
                    view=view,
                    actor=user_two,
                    virtual_path=placement.virtual_path,
                )
                second_metrics = build_organization_proposals(source=source, dry_run=False)

            self.assertEqual(first_metrics["proposals"], 0)
            self.assertEqual(second_metrics["proposals"], 1)
            proposal = MemoryFileOrganizationProposal.objects.get(source=source)
            self.assertEqual(proposal.proposed_rule["bucket"], "Договоры")

    def test_user_virtual_view_ui_does_not_move_file_or_grant_access(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "source"
            root.mkdir()
            source_file = root / "dogovor-2026.txt"
            source_file.write_text("Доступный файл для личной структуры.", encoding="utf-8")
            reader = User.objects.create_user(username="file-view-reader", password="pass")
            outsider = User.objects.create_user(username="file-view-outsider", password="pass")
            source = self.create_file_source(code="file_user_view", root=root)
            source_object = self.create_source_object(
                source=source,
                relative_path="dogovor-2026.txt",
                content_hash=sha256_file(source_file),
                size_bytes=source_file.stat().st_size,
                object_uri=str(source_file),
            )
            source_object.metadata = {"scope_tokens": [f"user:{reader.id}"]}
            source_object.save(update_fields=["metadata", "updated_at"])
            file_object = ensure_file_object_for_source_object(source_object)

            self.client.force_login(outsider)
            denied = self.client.post(
                reverse("filehub:user_file_views"),
                {"file_object_id": file_object.id, "virtual_path": "Мои/Договоры/dogovor-2026.txt"},
            )
            self.assertEqual(denied.status_code, 403)
            self.assertFalse(MemoryFileVirtualPlacement.objects.filter(file_object=file_object).exists())

            self.client.force_login(reader)
            response = self.client.post(
                reverse("filehub:user_file_views"),
                {"file_object_id": file_object.id, "virtual_path": "Мои/Договоры/dogovor-2026.txt"},
                follow=True,
            )

            self.assertEqual(response.status_code, 200)
            self.assertTrue(source_file.exists())
            placement = MemoryFileVirtualPlacement.objects.get(file_object=file_object)
            self.assertEqual(placement.virtual_path, "Мои/Договоры/dogovor-2026.txt")
            self.assertEqual(placement.view.owner_user, reader)
            self.assertEqual(placement.placement_source, MemoryFileVirtualPlacement.PlacementSource.USER_MANUAL)
            self.assertTrue(MemoryFileUsageEvent.objects.filter(file_object=file_object, actor=reader).exists())

    def test_managed_move_quarantines_source_and_requires_backup_checkpoint_before_purge(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "source"
            managed = Path(tmpdir) / "managed"
            root.mkdir()
            managed.mkdir()
            source_file = root / "dogovor-2026.txt"
            source_file.write_text("Договор 2026 для безопасного переноса.", encoding="utf-8")
            source = self.create_file_source(code="file_move_safe", root=root)
            source_object = self.create_source_object(
                source=source,
                relative_path="dogovor-2026.txt",
                content_hash=sha256_file(source_file),
                size_bytes=source_file.stat().st_size,
                object_uri=str(source_file),
            )
            file_object = ensure_file_object_for_source_object(source_object)
            admin = User.objects.create_user(username="file-move-admin", password="pass", is_staff=True)
            profiles = _file_organization_profiles(source_code=source.code, managed_root=managed, retention_days=30)
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                job = create_move_job_for_file(
                    file_object=file_object,
                    target_relative_path=f"by-function/contracts/{file_object.file_id}/dogovor-2026.txt",
                    approved_by=admin,
                )
                move_metrics = run_move_worker(source=source)
                job.refresh_from_db()

                self.assertEqual(move_metrics["moved"], 1)
                self.assertEqual(job.status, MemoryFileMoveJob.Status.SOURCE_QUARANTINED)
                self.assertFalse(source_file.exists())
                self.assertTrue(Path(job.target_storage_ref).exists())
                quarantine_ref = job.manifest["quarantine_storage_ref"]
                self.assertTrue(Path(quarantine_ref).exists())

                job.retention_until = timezone.now() - timedelta(days=1)
                job.save(update_fields=["retention_until", "updated_at"])
                blocked = purge_ready_source_files(source=source, backup_checkpoint_ref="")
                self.assertEqual(blocked["blocked"], 1)
                self.assertTrue(Path(quarantine_ref).exists())

                purged = purge_ready_source_files(source=source, backup_checkpoint_ref="snapshot-1")
                self.assertEqual(purged["purged"], 1)
                self.assertFalse(Path(quarantine_ref).exists())


class MemoryFileHubAdminObservabilityTests(TestCase):
    """Mirrors ``apps.memory.tests.MemoryAdminObservabilityTests`` for the
    11 models moved here by ADR-0030 decision 5 (packet 04)."""

    databases = RUNTIME_DATABASES

    def test_filehub_admin_registers_all_moved_models(self):
        for model in (
            MemoryFileObject,
            MemoryFileObjectVersion,
            MemoryFilePathAlias,
            MemoryFilePhysicalPlacement,
            MemoryFileVirtualView,
            MemoryFileVirtualRule,
            MemoryFileVirtualPlacement,
            MemoryFileUsageEvent,
            MemoryFileOrganizationProposal,
            MemoryFileOrganizationDecision,
            MemoryFileMoveJob,
        ):
            with self.subTest(model=model.__name__):
                self.assertIn(model, django_admin.site._registry)

    def test_filehub_admin_search_fields_do_not_include_storage_paths(self):
        path_fields = {"raw_path", "safe_path", "text_path"}

        for model in (
            MemoryFileObject,
            MemoryFileObjectVersion,
            MemoryFilePathAlias,
            MemoryFilePhysicalPlacement,
            MemoryFileVirtualView,
            MemoryFileVirtualRule,
            MemoryFileVirtualPlacement,
            MemoryFileUsageEvent,
            MemoryFileOrganizationProposal,
            MemoryFileOrganizationDecision,
            MemoryFileMoveJob,
        ):
            with self.subTest(model=model.__name__):
                model_admin = django_admin.site._registry[model]
                self.assertTrue(path_fields.isdisjoint(model_admin.search_fields))
