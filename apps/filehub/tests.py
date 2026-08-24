import os
import inspect
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.memory.document_ingestion import sha256_file
from apps.memory.models import MemoryIngestionIssue, MemorySource, MemorySourceObject
from apps.memory.policies import can_review_organization_memory, can_view_memory_review_queue
from apps.memory.tests import MemoryModelFactoryMixin

from .file_organization import (
    create_file_organization_issue,
    ensure_file_object_for_source_object,
    get_file_organization_profile,
    get_or_create_system_view,
    sync_file_objects_from_source_objects,
)
from .file_organization_baseline import build_baseline_virtual_structure
from .file_organization_incoming import process_incoming_folder
from .file_organization_move import (
    _claim_move_job,
    _membership_fingerprint,
    _create_system_planned_move_job,
    create_move_jobs_for_accepted_proposal,
    purge_ready_source_files,
    run_move_worker,
)
from .file_organization_stats import (
    _usage_candidates,
    apply_organization_proposal_decision,
    build_organization_proposals,
    record_file_usage_event,
)
from apps.memory.storage_backends import ManagedFSStorageBackend
from .selectors import can_access_file_object, can_access_source_for_organization, visible_file_objects
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
pytestmark = pytest.mark.integration


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

    def test_incoming_worker_blocks_symlink_outside_source_root(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "source"
            managed = Path(tmpdir) / "managed"
            incoming = root / "incoming" / "new"
            outside = Path(tmpdir) / "outside-secret.txt"
            incoming.mkdir(parents=True)
            managed.mkdir()
            outside.write_text("must not be indexed", encoding="utf-8")
            (incoming / "outside-link.txt").symlink_to(outside)
            source = self.create_file_source(code="file_incoming_symlink", root=root)
            profiles = _file_organization_profiles(source_code=source.code, managed_root=managed)

            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                metrics = process_incoming_folder(source=source, dry_run=False)

            self.assertEqual(metrics["blocked"], 1)
            self.assertEqual(metrics["issues"], 1)
            self.assertFalse(MemorySourceObject.objects.filter(source=source).exists())
            issue = MemoryIngestionIssue.objects.get(source=source, source_object__isnull=True)
            self.assertEqual(issue.severity, MemoryIngestionIssue.Severity.BLOCKER)
            self.assertEqual(issue.metadata["reason"], "unsafe_incoming_path")

    def test_incoming_worker_blocks_file_replaced_by_symlink_before_read(self):
        from . import file_organization_incoming as incoming_service

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "source"
            managed = Path(tmpdir) / "managed"
            incoming = root / "incoming" / "new"
            outside = Path(tmpdir) / "outside.txt"
            incoming.mkdir(parents=True)
            managed.mkdir()
            candidate = incoming / "candidate.txt"
            candidate.write_text("initial", encoding="utf-8")
            outside.write_text("foreign", encoding="utf-8")
            old_timestamp = timezone.now().timestamp() - 60
            os.utime(candidate, (old_timestamp, old_timestamp))
            source = self.create_file_source(code="file_incoming_swap", root=root)
            profiles = _file_organization_profiles(source_code=source.code, managed_root=managed)
            original_snapshot = incoming_service._safe_incoming_snapshot

            def swap_then_read(path, *, root):
                path.unlink()
                path.symlink_to(outside)
                return original_snapshot(path, root=root)

            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles), patch(
                "apps.filehub.file_organization_incoming._safe_incoming_snapshot",
                side_effect=swap_then_read,
            ):
                metrics = process_incoming_folder(source=source, dry_run=False)

            self.assertEqual(metrics["blocked"], 1)
            self.assertFalse(MemorySourceObject.objects.filter(source=source).exists())

    def test_quarantine_restores_source_when_post_move_hash_changes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "source.txt"
            source_path.write_text("stable", encoding="utf-8")
            backend = ManagedFSStorageBackend(root / "managed")
            expected_hash = sha256_file(source_path)
            with patch(
                "apps.memory.storage_backends.sha256_file",
                side_effect=[expected_hash, "different-after-move"],
            ):
                with self.assertRaises(ValueError):
                    backend.quarantine_source(
                        source_path,
                        quarantine_relative_path="quarantine/source.txt",
                        expected_hash=expected_hash,
                        expected_size=source_path.stat().st_size,
                    )
            self.assertTrue(source_path.exists())
            self.assertFalse((root / "managed" / "quarantine" / "source.txt").exists())

    def test_managed_backend_rejects_outside_and_symlink_storage_refs(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            managed_root = root / "managed"
            managed_root.mkdir()
            outside = root / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            link = managed_root / "outside-link.txt"
            link.symlink_to(outside)
            backend = ManagedFSStorageBackend(managed_root)
            expected_hash = sha256_file(outside)

            self.assertFalse(
                backend.verify(str(outside), expected_hash=expected_hash, expected_size=outside.stat().st_size)
            )
            self.assertFalse(
                backend.verify(str(link), expected_hash=expected_hash, expected_size=outside.stat().st_size)
            )
            with self.assertRaises(ValueError):
                backend.purge(str(outside))
            with self.assertRaises(ValueError):
                backend.purge(str(link))
            self.assertTrue(outside.exists())

    def test_structure_stats_respects_aggregation_threshold_before_creating_proposal(self):
        with TemporaryDirectory() as tmpdir:
            managed = Path(tmpdir) / "managed"
            managed.mkdir()
            source = self.create_file_source(code="file_stats_threshold")
            source_object = self.create_source_object(source=source, relative_path="contracts/dogovor-2026.txt")
            file_object = ensure_file_object_for_source_object(source_object)
            view = MemoryFileVirtualView.objects.create(
                source=source,
                view_kind=MemoryFileVirtualView.ViewKind.DEPARTMENT,
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
            admin.groups.add(Group.objects.create(name="admin"), Group.objects.create(name="memory_admin"))
            profiles = _file_organization_profiles(source_code=source.code, managed_root=managed, retention_days=30)
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                proposal = MemoryFileOrganizationProposal.objects.create(
                    source=source,
                    title="Move proposal",
                    status=MemoryFileOrganizationProposal.Status.PROPOSED,
                    proposed_rule={"bucket": "contracts"},
                    affected_file_count=1,
                    metadata={
                        "file_ids": [file_object.file_id],
                        "membership_fingerprint": _membership_fingerprint(
                            source=source,
                            bucket="contracts",
                            file_ids=[file_object.file_id],
                        ),
                    },
                )
                apply_organization_proposal_decision(
                    proposal=proposal,
                    actor=admin,
                    decision=MemoryFileOrganizationDecision.Decision.ACCEPT_FOR_PHYSICAL_MOVE,
                    create_jobs=True,
                )
                job = MemoryFileMoveJob.objects.get(proposal=proposal)
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


class MemoryFileHubScopeBoundaryTests(MemoryModelFactoryMixin, TestCase):
    databases = RUNTIME_DATABASES

    def setUp(self):
        self.technical_group = Group.objects.create(name="memory_admin")
        self.product_group = Group.objects.create(name="admin")
        self.actor = User.objects.create_user(username="filehub-scope-admin", password="pass", is_active=True)
        self.actor.groups.add(self.technical_group, self.product_group)

    def create_scoped_file(self, *, source_code, token, relative_path="docs/file.txt"):
        source = self.create_source(
            code=source_code,
            source_kind="local_path",
            domain="docs",
            scope_rule="authenticated_user",
            config={"source_ref": "/tmp/not-used", "file_organization_profile": "test_file_auto_org_v1"},
        )
        source_object = MemorySourceObject.objects.create(
            source=source,
            object_id=f"object:{source_code}:{relative_path}",
            object_uri=f"/tmp/{source_code}-{relative_path.replace('/', '-')}",
            relative_path=relative_path,
            file_name=Path(relative_path).name,
            extension=".txt",
            mime_type="text/plain",
            size_bytes=10,
            mtime=timezone.now(),
            content_hash=f"hash-{source_code}",
            metadata={"scope_tokens": [token]},
        )
        return source, ensure_file_object_for_source_object(source_object)

    def test_source_dashboard_never_uses_one_object_as_source_scope(self):
        source, file_object = self.create_scoped_file(source_code="filehub-source-a", token=f"user:{self.actor.pk}")
        other_source, _ = self.create_scoped_file(source_code="filehub-source-b", token="user:other")
        self.client.force_login(self.actor)
        response = self.client.get(reverse("filehub:file_organization"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["source"].code for row in response.context["sources"]},
            {source.code},
        )
        self.assertEqual([row["file_id"] for row in response.context["placements"]], [])

        # A source-level adapter policy is not inferred from one visible object.
        source.config = {**source.config, "access_policy": {"mode": "adapter_check"}}
        source.save(update_fields=["config"])
        response = self.client.get(reverse("filehub:file_organization"))
        self.assertNotIn(source.code, {row["source"].code for row in response.context["sources"]})

    def test_revoked_current_object_access_hides_saved_user_placement(self):
        source, file_object = self.create_scoped_file(source_code="filehub-revoked", token=f"user:{self.actor.pk}")
        view = MemoryFileVirtualView.objects.create(
            source=source,
            view_kind=MemoryFileVirtualView.ViewKind.USER,
            slug=f"user-{self.actor.pk}",
            title="Personal",
            owner_user=self.actor,
            status=MemoryFileVirtualView.Status.ACTIVE,
        )
        MemoryFileVirtualPlacement.objects.create(
            view=view,
            file_object=file_object,
            virtual_path="Мои/file.txt",
            placement_source=MemoryFileVirtualPlacement.PlacementSource.USER_MANUAL,
            status=MemoryFileVirtualPlacement.Status.ACCEPTED,
        )
        self.client.force_login(self.actor)
        self.assertEqual(len(self.client.get(reverse("filehub:user_file_views")).context["placements"]), 1)
        source_object = file_object.current_version.source_object
        source_object.metadata = {"scope_tokens": ["user:revoked"]}
        source_object.save(update_fields=["metadata", "updated_at"])
        response = self.client.get(reverse("filehub:user_file_views"))
        self.assertEqual(len(response.context["placements"]), 0)

    def test_physical_move_rejects_empty_missing_foreign_and_partial_sets_without_jobs(self):
        source, file_object = self.create_scoped_file(source_code="filehub-exact", token=f"user:{self.actor.pk}")
        proposal = MemoryFileOrganizationProposal.objects.create(
            source=source,
            title="Exact set",
            status=MemoryFileOrganizationProposal.Status.ACCEPTED_PHYSICAL,
            metadata={"file_ids": []},
        )
        with self.assertRaises(ValidationError):
            create_move_jobs_for_accepted_proposal(proposal=proposal, approved_by=self.actor)
        self.assertEqual(MemoryFileMoveJob.objects.count(), 0)

        proposal.metadata = {"file_ids": [file_object.file_id, "file:foreign"]}
        proposal.save(update_fields=["metadata", "updated_at"])
        with self.assertRaises(ValidationError):
            create_move_jobs_for_accepted_proposal(proposal=proposal, approved_by=self.actor)
        self.assertEqual(MemoryFileMoveJob.objects.count(), 0)

        proposal.metadata = {"file_ids": [file_object.file_id]}
        proposal.affected_file_count = 1
        proposal.proposed_rule = {"bucket": "docs"}
        proposal.metadata["membership_fingerprint"] = _membership_fingerprint(
            source=source,
            bucket="docs",
            file_ids=[file_object.file_id],
        )
        proposal.save(update_fields=["metadata", "affected_file_count", "proposed_rule", "updated_at"])
        # The test fixture has no physical source file/hash, so validation
        # rejects the whole batch rather than creating a partial job.
        file_object.current_version.sha256 = ""
        file_object.current_version.save(update_fields=["sha256", "updated_at"])
        with self.assertRaises((ValueError, ValidationError)):
            create_move_jobs_for_accepted_proposal(proposal=proposal, approved_by=self.actor)
        self.assertEqual(MemoryFileMoveJob.objects.count(), 0)

    def test_decision_direct_and_http_share_product_and_technical_authority(self):
        source, _file_object = self.create_scoped_file(source_code="filehub-parity", token=f"user:{self.actor.pk}")
        proposal = MemoryFileOrganizationProposal.objects.create(
            source=source,
            title="Parity",
            status=MemoryFileOrganizationProposal.Status.PROPOSED,
            metadata={"file_ids": ["file:missing"]},
        )
        outsider = User.objects.create_user(username="filehub-outsider", password="pass", is_active=True)
        with self.assertRaises(PermissionDenied):
            from .file_organization_stats import apply_organization_proposal_decision

            apply_organization_proposal_decision(
                proposal=proposal,
                actor=outsider,
                decision=MemoryFileOrganizationDecision.Decision.REJECT,
            )
        self.client.force_login(outsider)
        response = self.client.post(
            reverse("filehub:file_organization_proposal_action", kwargs={"pk": proposal.pk}),
            {"decision": MemoryFileOrganizationDecision.Decision.REJECT},
        )
        self.assertEqual(response.status_code, 403)

    def test_worker_claim_is_single_use_and_unclaimed_execution_is_denied(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "source"
            managed = Path(tmpdir) / "managed"
            root.mkdir()
            managed.mkdir()
            path = root / "claim.txt"
            path.write_text("claim me", encoding="utf-8")
            source = self.create_source(
                code="filehub-claim",
                source_kind="local_path",
                domain="docs",
                scope_rule="authenticated_user",
                config={"source_ref": str(root), "file_organization_profile": "test_file_auto_org_v1"},
            )
            source_object = MemorySourceObject.objects.create(
                source=source,
                object_id="object:filehub-claim:claim.txt",
                object_uri=str(path),
                relative_path="claim.txt",
                file_name="claim.txt",
                extension=".txt",
                mime_type="text/plain",
                content_hash=sha256_file(path),
                size_bytes=path.stat().st_size,
                mtime=timezone.now(),
                metadata={"scope_tokens": [f"user:{self.actor.pk}"]},
            )
            file_object = ensure_file_object_for_source_object(source_object)
            profiles = _file_organization_profiles(source_code=source.code, managed_root=managed)
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                job = _create_system_planned_move_job(
                    file_object=file_object,
                    target_relative_path="managed/claim.txt",
                )
                job.status = MemoryFileMoveJob.Status.APPROVED
                job.save(update_fields=["status", "updated_at"])
                claimed = _claim_move_job(job.pk)
                self.assertIsNotNone(claimed)
                _claimed_job, claim_token = claimed
                self.assertIsNone(_claim_move_job(job.pk))
                with self.assertRaises(ValidationError):
                    # A direct execution cannot bypass the atomic claim step.
                    from .file_organization_move import execute_move_job

                    execute_move_job(job_id=job.pk)
                from .file_organization_move import execute_move_job

                self.assertEqual(
                    execute_move_job(job_id=job.pk, claim_token=claim_token),
                    "moved",
                )
                with self.assertRaises(ValidationError):
                    execute_move_job(job_id=job.pk, claim_token=claim_token)

    def test_actor_matrix_inactive_staff_technical_product_and_root(self):
        inactive = User.objects.create_user(username="filehub-inactive", password="pass", is_active=False)
        inactive.groups.add(self.technical_group, self.product_group)
        staff = User.objects.create_user(username="filehub-staff", password="pass", is_staff=True)
        technical = User.objects.create_user(username="filehub-technical", password="pass")
        technical.groups.add(self.technical_group)
        product = User.objects.create_user(username="filehub-product", password="pass")
        product.groups.add(self.product_group)
        root = User.objects.create_superuser(username="filehub-root", password="pass")

        self.assertFalse(can_view_memory_review_queue(inactive))
        self.assertFalse(can_review_organization_memory(inactive))
        self.assertFalse(can_view_memory_review_queue(staff))
        self.assertFalse(can_review_organization_memory(staff))
        self.assertTrue(can_view_memory_review_queue(technical))
        self.assertFalse(can_review_organization_memory(technical))
        self.assertFalse(can_view_memory_review_queue(product))
        self.assertFalse(can_review_organization_memory(product))
        self.assertTrue(can_view_memory_review_queue(root))
        self.assertTrue(can_review_organization_memory(root))

        self.actor.groups.remove(self.product_group)
        self.assertFalse(can_review_organization_memory(self.actor))

    def test_file_selectors_use_fresh_superuser_state(self):
        root = User.objects.create_superuser(username="filehub-stale-root", password="pass")
        stale_root = User.objects.get(pk=root.pk)
        source, file_object = self.create_scoped_file(
            source_code="filehub-stale-root-source",
            token=f"user:{self.actor.pk}",
        )
        root.is_superuser = False
        root.save(update_fields=["is_superuser"])

        self.assertFalse(can_access_file_object(stale_root, file_object))
        self.assertFalse(can_access_source_for_organization(stale_root, source))
        self.assertEqual(list(visible_file_objects(stale_root, source=source)), [])

    def test_access_lock_is_taken_before_nested_actor_write(self):
        from apps.core.file_locks import access_control_write_lock_path, memory_source_lifecycle_lock_path
        from .file_organization import save_user_virtual_placement
        from .file_organization_stats import record_file_usage_event

        lock = patch("apps.filehub.file_organization.exclusive_file_lock")
        with lock as lock_mock, patch("apps.filehub.file_organization._save_user_virtual_placement_locked", return_value=None):
            lock_mock.return_value.__enter__.return_value = None
            save_user_virtual_placement(actor=self.actor, file_object_id=999999, virtual_path="x")
            self.assertEqual(lock_mock.call_count, 2)
            self.assertEqual(lock_mock.call_args_list[0].args[0], access_control_write_lock_path())
            self.assertEqual(lock_mock.call_args_list[1].args[0], memory_source_lifecycle_lock_path())

        with patch("apps.filehub.file_organization_stats.exclusive_file_lock") as event_lock:
            event_lock.return_value.__enter__.return_value = None
            with self.assertRaises(PermissionDenied):
                record_file_usage_event(source=MemorySource(code="missing"), event_kind="file_opened")
            self.assertEqual(event_lock.call_count, 2)
            self.assertEqual(event_lock.call_args_list[0].args[0], access_control_write_lock_path())
            self.assertEqual(event_lock.call_args_list[1].args[0], memory_source_lifecycle_lock_path())

    def test_actor_aware_filehub_wrappers_translate_lock_timeout_to_validation_error(self):
        from apps.core.file_locks import FileLockTimeoutError
        from . import file_organization, file_organization_move, file_organization_stats

        cases = (
            (
                file_organization,
                file_organization.save_user_virtual_placement,
                {"actor": self.actor, "file_object_id": 1, "virtual_path": "docs/example.txt"},
            ),
            (
                file_organization_stats,
                file_organization_stats.record_file_usage_event,
                {"source": MemorySource(code="lock-timeout-source"), "event_kind": "file_opened", "actor": self.actor},
            ),
            (
                file_organization_stats,
                file_organization_stats.apply_organization_proposal_decision,
                {
                    "proposal": MemoryFileOrganizationProposal(pk=1),
                    "actor": self.actor,
                    "decision": MemoryFileOrganizationDecision.Decision.REJECT,
                },
            ),
            (
                file_organization_move,
                file_organization_move.create_move_jobs_for_accepted_proposal,
                {"proposal": MemoryFileOrganizationProposal(pk=1), "approved_by": self.actor},
            ),
        )
        for module, operation, kwargs in cases:
            with self.subTest(operation=operation.__name__):
                with patch.object(module, "exclusive_file_lock", side_effect=FileLockTimeoutError("lock held")):
                    with self.assertRaisesRegex(ValidationError, "Файловый контур занят") as raised:
                        operation(**kwargs)
                self.assertIsInstance(raised.exception.__cause__, FileLockTimeoutError)

    def test_duplicate_jobs_for_same_file_different_target_are_rejected_at_approval(self):
        source, file_object = self.create_scoped_file(
            source_code="filehub-duplicate",
            token=f"user:{self.actor.pk}",
        )
        with TemporaryDirectory() as tmpdir:
            profiles = _file_organization_profiles(source_code=source.code, managed_root=Path(tmpdir))
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                first = _create_system_planned_move_job(
                    file_object=file_object,
                    target_relative_path="managed/first.txt",
                )
                proposal = MemoryFileOrganizationProposal.objects.create(
                    source=source,
                    title="duplicate proposal",
                    status=MemoryFileOrganizationProposal.Status.ACCEPTED_PHYSICAL,
                    proposed_rule={"bucket": "docs"},
                    affected_file_count=1,
                    metadata={
                        "file_ids": [file_object.file_id],
                        "membership_fingerprint": _membership_fingerprint(
                            source=source, bucket="docs", file_ids=[file_object.file_id]
                        ),
                    },
                )
                with self.assertRaises(ValidationError):
                    create_move_jobs_for_accepted_proposal(proposal=proposal, approved_by=self.actor)
                self.assertEqual(first.status, MemoryFileMoveJob.Status.PLANNED)

    def test_claim_lock_order_and_validator_reject_foreign_or_unsafe_chain(self):
        from .file_organization_move import _claim_move_job, _validate_job_source_state

        source, file_object = self.create_scoped_file(
            source_code="filehub-validator",
            token=f"user:{self.actor.pk}",
        )
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "source"
            root.mkdir()
            safe_path = root / "docs" / "file.txt"
            safe_path.parent.mkdir()
            safe_path.write_text("validator source", encoding="utf-8")
            source.config = {**(source.config or {}), "source_ref": str(root)}
            source.save(update_fields=["config", "updated_at"])
            source_object = file_object.current_version.source_object
            source_object.object_uri = str(safe_path)
            source_object.content_hash = sha256_file(safe_path)
            source_object.size_bytes = safe_path.stat().st_size
            source_object.save(update_fields=["object_uri", "content_hash", "size_bytes", "updated_at"])
            version = file_object.current_version
            version.sha256 = source_object.content_hash
            version.size_bytes = source_object.size_bytes
            version.storage_ref = str(safe_path)
            version.save(update_fields=["sha256", "size_bytes", "storage_ref", "updated_at"])
            placement = file_object.current_physical_placement
            placement.physical_ref = str(safe_path)
            placement.save(update_fields=["physical_ref", "updated_at"])
            job = None
            profiles = _file_organization_profiles(source_code=source.code, managed_root=Path(tmpdir))
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                job = _create_system_planned_move_job(file_object=file_object, target_relative_path="managed/a.txt")
                job.expected_sha256 = version.sha256
                job.expected_size_bytes = version.size_bytes
                job.save(update_fields=["expected_sha256", "expected_size_bytes", "updated_at"])
                job.status = MemoryFileMoveJob.Status.APPROVED
                job.save(update_fields=["status", "updated_at"])
                self.assertIsNotNone(_claim_move_job(job.pk))
                claim_source = inspect.getsource(_claim_move_job)
                self.assertIn("source = MemorySource.objects.select_for_update", claim_source)
                self.assertIn("file_object = MemoryFileObject.objects.select_for_update", claim_source)
                self.assertIn("MemoryFileMoveJob.objects.select_for_update()", claim_source)
                self.assertLess(
                    claim_source.index("source = MemorySource.objects.select_for_update"),
                    claim_source.index("MemoryFileMoveJob.objects.select_for_update()"),
                )

                foreign_source = self.create_source(
                    code="filehub-validator-foreign",
                    source_kind="local_path",
                    domain="docs",
                    scope_rule="authenticated_user",
                    config={"source_ref": str(root)},
                )
                foreign_object = MemorySourceObject.objects.create(
                    source=foreign_source,
                    object_id="foreign:validator",
                    object_uri=str(root / "foreign.txt"),
                    relative_path="docs/file.txt",
                    file_name="file.txt",
                    extension=".txt",
                    mime_type="text/plain",
                    content_hash=source_object.content_hash,
                    size_bytes=source_object.size_bytes,
                    mtime=timezone.now(),
                    metadata={"scope_tokens": [f"user:{self.actor.pk}"]},
                )
                placement.source_object = foreign_object
                placement.physical_ref = foreign_object.object_uri
                placement.save(update_fields=["source_object", "physical_ref", "updated_at"])
                with self.assertRaises(ValidationError):
                    _validate_job_source_state(job)

                placement.source_object = source_object
                placement.physical_ref = str(safe_path)
                placement.save(update_fields=["source_object", "physical_ref", "updated_at"])
                file_object.current_physical_placement = None
                file_object.save(update_fields=["current_physical_placement", "updated_at"])
                with self.assertRaises(ValidationError):
                    _validate_job_source_state(job)
                file_object.current_physical_placement = placement
                file_object.save(update_fields=["current_physical_placement", "updated_at"])

                outside = Path(tmpdir) / "outside.txt"
                outside.write_text("outside", encoding="utf-8")
                source_object.object_uri = str(outside)
                source_object.save(update_fields=["object_uri", "updated_at"])
                placement.physical_ref = str(outside)
                placement.save(update_fields=["physical_ref", "updated_at"])
                with self.assertRaises(ValidationError):
                    _validate_job_source_state(job)

                symlink = root / "docs" / "link.txt"
                symlink.symlink_to(outside)
                source_object.object_uri = str(symlink)
                source_object.save(update_fields=["object_uri", "updated_at"])
                placement.physical_ref = str(symlink)
                placement.save(update_fields=["physical_ref", "updated_at"])
                with self.assertRaises(ValidationError):
                    _validate_job_source_state(job)

    def test_execute_profile_is_canonical_and_backend_mismatch_requires_review(self):
        from .file_organization_move import execute_move_job

        self.assertNotIn("profile", inspect.signature(execute_move_job).parameters)
        source, file_object = self.create_scoped_file(
            source_code="filehub-s3",
            token=f"user:{self.actor.pk}",
        )
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "source"
            root.mkdir()
            path = root / "docs" / "file.txt"
            path.parent.mkdir()
            path.write_text("canonical backend check", encoding="utf-8")
            source.config = {**(source.config or {}), "source_ref": str(root)}
            source.save(update_fields=["config", "updated_at"])
            source_object = file_object.current_version.source_object
            source_object.object_uri = str(path)
            source_object.content_hash = sha256_file(path)
            source_object.size_bytes = path.stat().st_size
            source_object.save(update_fields=["object_uri", "content_hash", "size_bytes", "updated_at"])
            version = file_object.current_version
            version.sha256 = source_object.content_hash
            version.size_bytes = source_object.size_bytes
            version.storage_ref = str(path)
            version.save(update_fields=["sha256", "size_bytes", "storage_ref", "updated_at"])
            placement = file_object.current_physical_placement
            placement.physical_ref = str(path)
            placement.save(update_fields=["physical_ref", "updated_at"])
            profiles = _file_organization_profiles(source_code=source.code, managed_root=Path(tmpdir))
            profiles["profiles"]["test_file_auto_org_v1"]["storage_backend"] = "s3_compatible"
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                job = MemoryFileMoveJob.objects.create(
                    source=source,
                    file_object=file_object,
                    source_placement=placement,
                    idempotency_key="profile-mismatch-test",
                    status=MemoryFileMoveJob.Status.COPY_STAGED,
                    target_relative_path="managed/a.txt",
                    expected_sha256=file_object.current_version.sha256,
                    expected_size_bytes=file_object.current_version.size_bytes,
                    started_at=timezone.now(),
                    manifest={"claim_token": "token", "profile_id": "test_file_auto_org_v1"},
                )
                self.assertEqual(execute_move_job(job_id=job.pk, claim_token="token"), "needs_review")
                job.refresh_from_db()
                self.assertEqual(job.status, MemoryFileMoveJob.Status.NEEDS_REVIEW)

    def test_stale_copy_staged_recovery_and_purge_guards(self):
        source, file_object = self.create_scoped_file(
            source_code="filehub-recovery",
            token=f"user:{self.actor.pk}",
        )
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            profiles = _file_organization_profiles(source_code=source.code, managed_root=root)
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                job = _create_system_planned_move_job(file_object=file_object, target_relative_path="managed/a.txt")
                job.status = MemoryFileMoveJob.Status.COPY_STAGED
                job.started_at = timezone.now() - timedelta(minutes=30)
                job.manifest = {"claim_token": "stale"}
                job.save(update_fields=["status", "started_at", "manifest", "updated_at"])
                run_move_worker(source=source)
                job.refresh_from_db()
                self.assertEqual(job.status, MemoryFileMoveJob.Status.NEEDS_REVIEW)
                self.assertEqual(job.error_message, "stale_copy_staged_claim")

                job.status = MemoryFileMoveJob.Status.COPY_STAGED
                job.started_at = timezone.now() - timedelta(minutes=30)
                job.manifest = {"claim_token": "stale", "execution_started_at": timezone.now().isoformat()}
                job.save(update_fields=["status", "started_at", "manifest", "updated_at"])
                run_move_worker(source=source)
                job.refresh_from_db()
                self.assertEqual(job.status, MemoryFileMoveJob.Status.NEEDS_REVIEW)
                self.assertEqual(job.error_message, "stale_execution_started_manual_reconciliation")

                job.status = MemoryFileMoveJob.Status.SOURCE_QUARANTINED
                job.retention_until = timezone.now() - timedelta(days=1)
                job.manifest = {"quarantine_storage_ref": str(root / "outside" / "q.txt")}
                job.save(update_fields=["status", "retention_until", "manifest", "updated_at"])
                result = purge_ready_source_files(source=source, backup_checkpoint_ref="snapshot")
                self.assertEqual(result["purged"], 0)
                job.refresh_from_db()
                self.assertEqual(job.status, MemoryFileMoveJob.Status.NEEDS_REVIEW)

    def test_public_actorless_usage_and_foreign_view_are_fail_closed(self):
        source, file_object = self.create_scoped_file(
            source_code="filehub-event-source",
            token=f"user:{self.actor.pk}",
        )
        foreign = self.create_source(code="filehub-event-foreign", source_kind="local_path", domain="docs", scope_rule="authenticated_user", config={})
        foreign_view = MemoryFileVirtualView.objects.create(
            source=foreign,
            view_kind=MemoryFileVirtualView.ViewKind.DEPARTMENT,
            slug="foreign",
            title="Foreign",
            status=MemoryFileVirtualView.Status.ACTIVE,
        )
        with self.assertRaises(PermissionDenied):
            record_file_usage_event(source=source, view=foreign_view, event_kind="file_opened", actor=None)
        MemoryFileUsageEvent.objects.create(source=source, view=foreign_view, event_kind="file_opened", safe_path_bucket="Foreign")
        self.assertEqual(_usage_candidates(source), {})

    def test_final_proposal_not_reopened_and_foreign_dashboard_relation_hidden(self):
        source, file_object = self.create_scoped_file(
            source_code="filehub-final",
            token=f"user:{self.actor.pk}",
        )
        view = MemoryFileVirtualView.objects.create(
            source=source,
            view_kind=MemoryFileVirtualView.ViewKind.DEPARTMENT,
            slug="docs",
            title="Docs",
            status=MemoryFileVirtualView.Status.ACTIVE,
        )
        placement = MemoryFileVirtualPlacement.objects.create(
            view=view,
            file_object=file_object,
            virtual_path="Docs/file.txt",
            placement_source=MemoryFileVirtualPlacement.PlacementSource.USER_MANUAL,
            status=MemoryFileVirtualPlacement.Status.ACCEPTED,
        )
        record_file_usage_event(source=source, event_kind=MemoryFileUsageEvent.EventKind.FILE_OPENED, file_object=file_object, view=view, actor=self.actor, virtual_path=placement.virtual_path)
        with TemporaryDirectory() as tmpdir:
            profiles = _file_organization_profiles(source_code=source.code, managed_root=Path(tmpdir), min_users=1, min_events=1)
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                build_organization_proposals(source=source)
                proposal = MemoryFileOrganizationProposal.objects.get(source=source)
                proposal.status = MemoryFileOrganizationProposal.Status.ACCEPTED_VIRTUAL
                proposal.save(update_fields=["status", "updated_at"])
                build_organization_proposals(source=source)
                proposal.refresh_from_db()
                self.assertEqual(proposal.status, MemoryFileOrganizationProposal.Status.ACCEPTED_VIRTUAL)
                self.assertEqual(MemoryFileOrganizationProposal.objects.filter(source=source).count(), 2)

        foreign = self.create_source(code="filehub-final-foreign", source_kind="local_path", domain="docs", scope_rule="authenticated_user", config={})
        foreign_view = MemoryFileVirtualView.objects.create(
            source=foreign,
            view_kind=MemoryFileVirtualView.ViewKind.DEPARTMENT,
            slug="foreign",
            title="Foreign",
            status=MemoryFileVirtualView.Status.ACTIVE,
        )
        MemoryFileVirtualPlacement.objects.create(
            view=foreign_view,
            file_object=file_object,
            virtual_path="Foreign/file.txt",
            placement_source=MemoryFileVirtualPlacement.PlacementSource.USER_MANUAL,
            status=MemoryFileVirtualPlacement.Status.ACCEPTED,
        )
        self.client.force_login(self.actor)
        response = self.client.get(reverse("filehub:file_organization"))
        visible_placements = list(response.context["placements"])
        self.assertEqual([item.pk for item in visible_placements], [placement.pk])
        self.assertNotIn("Foreign/file.txt", [item.virtual_path for item in visible_placements])

    def test_admin_operational_models_are_readonly_and_reference_models_are_superuser_reserve(self):
        staff = User.objects.create_user(username="filehub-admin-staff", password="pass", is_staff=True)
        root = User.objects.create_superuser(username="filehub-admin-root", password="pass")
        staff_request = SimpleNamespace(user=staff)
        root_request = SimpleNamespace(user=root)
        for model in (MemoryFileVirtualPlacement, MemoryFilePhysicalPlacement, MemoryFileUsageEvent, MemoryFileOrganizationProposal, MemoryFileOrganizationDecision, MemoryFileMoveJob):
            model_admin = django_admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(staff_request))
            self.assertFalse(model_admin.has_change_permission(staff_request))
            self.assertFalse(model_admin.has_delete_permission(staff_request))
            self.assertFalse(model_admin.has_add_permission(root_request))
            self.assertFalse(model_admin.has_change_permission(root_request))
            self.assertFalse(model_admin.has_delete_permission(root_request))
        reference_admin = django_admin.site._registry[MemoryFileVirtualRule]
        self.assertFalse(reference_admin.has_change_permission(staff_request))
        self.assertTrue(reference_admin.has_change_permission(root_request))

    def test_empty_and_disabled_sources_are_not_source_wide(self):
        empty = self.create_source(
            code="filehub-empty",
            source_kind="local_path",
            domain="docs",
            scope_rule="authenticated_user",
            config={"source_ref": "/tmp/empty", "file_organization_profile": "test_file_auto_org_v1"},
        )
        self.assertFalse(can_access_source_for_organization(self.actor, empty))
        source, _file_object = self.create_scoped_file(source_code="filehub-disabled", token=f"user:{self.actor.pk}")
        with TemporaryDirectory() as tmpdir:
            profiles = _file_organization_profiles(source_code=source.code, managed_root=Path(tmpdir), enabled=False)
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                with self.assertRaises((TypeError, ValueError)):
                    build_organization_proposals(source=source)

    def test_move_job_creation_rejects_tampered_approved_snapshot(self):
        from .file_organization_move import _create_move_jobs_for_accepted_proposal_locked

        source, file_object = self.create_scoped_file(source_code="filehub-snapshot-tamper", token=f"user:{self.actor.pk}")
        proposal = MemoryFileOrganizationProposal.objects.create(
            source=source,
            title="Snapshot tamper",
            status=MemoryFileOrganizationProposal.Status.ACCEPTED_PHYSICAL,
            proposed_rule={"bucket": "docs"},
            affected_file_count=1,
            metadata={
                "file_ids": [file_object.file_id],
                "membership_fingerprint": _membership_fingerprint(source=source, bucket="docs", file_ids=[file_object.file_id]),
            },
        )
        MemoryFileOrganizationDecision.objects.create(
            proposal=proposal,
            actor=self.actor,
            decision=MemoryFileOrganizationDecision.Decision.ACCEPT_FOR_PHYSICAL_MOVE,
            safe_metadata={"approved_snapshot": {"source_id": source.pk, "source_code": source.code, "bucket": "docs", "file_ids": ["foreign"], "objects": []}},
        )
        with TemporaryDirectory() as tmpdir:
            profiles = _file_organization_profiles(source_code=source.code, managed_root=Path(tmpdir))
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                with self.assertRaises(ValidationError):
                    _create_move_jobs_for_accepted_proposal_locked(proposal=proposal, approved_by=self.actor)
                invalid = MemoryFileOrganizationProposal.objects.create(
                    source=source,
                    title="Invalid snapshot before acceptance",
                    status=MemoryFileOrganizationProposal.Status.PROPOSED,
                    proposed_rule={"bucket": "docs"},
                    affected_file_count=2,
                    metadata={"file_ids": [file_object.file_id], "membership_fingerprint": "sha256:wrong"},
                )
                with self.assertRaises(ValidationError):
                    apply_organization_proposal_decision(
                        proposal=invalid,
                        actor=self.actor,
                        decision=MemoryFileOrganizationDecision.Decision.ACCEPT_FOR_PHYSICAL_MOVE,
                    )
                invalid.refresh_from_db()
                self.assertEqual(invalid.status, MemoryFileOrganizationProposal.Status.PROPOSED)
                self.assertFalse(invalid.decisions.exists())

    def test_recovery_covers_verified_and_managed_active_without_losing_phase_marker(self):
        from .file_organization_move import _recover_stale_move_jobs

        source, file_object = self.create_scoped_file(source_code="filehub-recovery-phases", token=f"user:{self.actor.pk}")
        with TemporaryDirectory() as tmpdir:
            profiles = _file_organization_profiles(source_code=source.code, managed_root=Path(tmpdir))
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                job = _create_system_planned_move_job(file_object=file_object, target_relative_path="managed/a.txt")
                for status, phase in ((MemoryFileMoveJob.Status.VERIFIED, "VERIFIED"), (MemoryFileMoveJob.Status.MANAGED_ACTIVE, "MANAGED_ACTIVE")):
                    job.status = status
                    job.started_at = timezone.now() - timedelta(minutes=30)
                    job.manifest = {"claim_token": "keep", "execution_started_at": "marker", "phase": phase}
                    job.save(update_fields=["status", "started_at", "manifest", "updated_at"])
                    _recover_stale_move_jobs(source=source)
                    job.refresh_from_db()
                    self.assertEqual(job.status, MemoryFileMoveJob.Status.NEEDS_REVIEW)
                    self.assertEqual(job.manifest["execution_started_at"], "marker")
                    self.assertEqual(job.manifest["stale_recovery_phase"], status)

    def test_decision_and_job_creation_use_source_before_proposal_lock_order(self):
        from .file_organization_move import _create_move_jobs_for_accepted_proposal_locked
        from .file_organization_stats import _apply_organization_proposal_decision_locked

        for operation in (_apply_organization_proposal_decision_locked, _create_move_jobs_for_accepted_proposal_locked):
            source = inspect.getsource(operation)
            self.assertLess(
                source.index("source = MemorySource.objects.select_for_update"),
                source.index("MemoryFileOrganizationProposal.objects.select_for_update"),
            )
            self.assertIn("values(\"source_id\")", source)
        recovery = inspect.getsource(__import__("apps.filehub.file_organization_move", fromlist=["_recover_stale_move_jobs"])._recover_stale_move_jobs)
        self.assertLess(
            recovery.index("MemorySource.objects.select_for_update"),
            recovery.index("MemoryFileObject.objects.select_for_update"),
        )
        self.assertLess(
            recovery.index("MemoryFileObject.objects.select_for_update"),
            recovery.index("MemoryFileMoveJob.objects.select_for_update"),
        )

    def test_memory_workers_use_lifecycle_lock_and_actor_decisions_use_access_then_memory(self):
        from . import file_organization, file_organization_baseline, file_organization_incoming, file_organization_move, file_organization_stats

        for operation in (
            file_organization.ensure_file_object_for_source_object,
            file_organization.sync_file_objects_from_source_objects,
            file_organization_baseline.build_baseline_virtual_structure,
            file_organization_incoming.process_incoming_folder,
            file_organization_stats.build_organization_proposals,
            file_organization_move.run_move_worker,
            file_organization_move.execute_move_job,
            file_organization_move.purge_ready_source_files,
        ):
            source = inspect.getsource(operation)
            self.assertIn("memory_source_lifecycle_lock_path", source, operation.__name__)
            self.assertNotIn("access_control_write_lock_path", source, operation.__name__)

        for operation in (
            file_organization.save_user_virtual_placement,
            file_organization_stats.record_file_usage_event,
            file_organization_stats.apply_organization_proposal_decision,
            file_organization_move.create_move_jobs_for_accepted_proposal,
        ):
            source = inspect.getsource(operation)
            self.assertLess(
                source.index("access_control_write_lock_path"),
                source.index("memory_source_lifecycle_lock_path"),
                operation.__name__,
            )

    def test_source_statuses_gate_source_wide_access_and_profiles(self):
        source, _file_object = self.create_scoped_file(source_code="filehub-source-statuses", token=f"user:{self.actor.pk}")
        from .file_organization import get_file_organization_profile

        for status in MemorySource.Status.values:
            source.status = status
            source.save(update_fields=["status", "updated_at"])
            expected = status == MemorySource.Status.ENABLED
            self.assertEqual(can_access_source_for_organization(self.actor, source), expected)
            with TemporaryDirectory() as tmpdir:
                profiles = _file_organization_profiles(source_code=source.code, managed_root=Path(tmpdir))
                with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                    if expected:
                        self.assertTrue(get_file_organization_profile(source).enabled)
                    else:
                        with self.assertRaises(ValueError):
                            get_file_organization_profile(source)

    def test_disabled_source_cannot_be_reenabled_by_public_writer_flag(self):
        source, _file_object = self.create_scoped_file(
            source_code="filehub-disabled-writer",
            token=f"user:{self.actor.pk}",
        )
        source.status = MemorySource.Status.DISABLED
        source.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValueError):
            get_file_organization_profile(source, require_enabled=False)
        with self.assertRaises(ValueError):
            build_baseline_virtual_structure(source=source, dry_run=True, require_enabled=False)
        with self.assertRaises(ValueError):
            process_incoming_folder(source=source, dry_run=True, require_enabled=False)
        with self.assertRaises(ValueError):
            build_organization_proposals(source=source, dry_run=True, require_enabled=False)
        with self.assertRaises(ValueError):
            run_move_worker(source=source, dry_run=True, require_enabled=False)
        with self.assertRaises(ValueError):
            purge_ready_source_files(source=source, dry_run=True, require_enabled=False)

        with self.assertRaises(ValueError):
            get_or_create_system_view(
                source=source,
                view_kind=MemoryFileVirtualView.ViewKind.BASELINE_AUTO,
                slug="disabled",
                title="Disabled",
            )
        with self.assertRaises(ValueError):
            create_file_organization_issue(
                source=source,
                source_object=None,
                message="should be denied",
                metadata={},
            )

    def test_sync_after_physical_move_never_resurrects_source_current_state(self):
        source, file_object = self.create_scoped_file(
            source_code="filehub-sync-no-resurrection",
            token=f"user:{self.actor.pk}",
        )
        source_object = file_object.current_version.source_object
        source_placement = file_object.current_physical_placement
        managed = MemoryFilePhysicalPlacement.objects.create(
            file_object=file_object,
            source_object=source_object,
            storage_backend=MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS,
            physical_ref="/managed/file.txt",
            relative_path="managed/file.txt",
            path_role=MemoryFilePhysicalPlacement.PathRole.MANAGED_CURRENT,
            placement_status=MemoryFilePhysicalPlacement.PlacementStatus.ACTIVE,
            is_current=True,
        )
        source_placement.is_current = False
        source_placement.placement_status = MemoryFilePhysicalPlacement.PlacementStatus.MIGRATED
        source_placement.save(update_fields=["is_current", "placement_status", "updated_at"])
        file_object.current_physical_placement = managed
        file_object.lifecycle_status = MemoryFileObject.LifecycleStatus.MANAGED_ACTIVE
        file_object.save(update_fields=["current_physical_placement", "lifecycle_status", "updated_at"])

        with self.settings(
            LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=_file_organization_profiles(
                source_code=source.code,
                managed_root=Path("/tmp/filehub-sync-no-resurrection"),
            )
        ):
            sync_file_objects_from_source_objects(source=source)

        file_object.refresh_from_db()
        managed.refresh_from_db()
        source_placement.refresh_from_db()
        self.assertEqual(file_object.current_physical_placement_id, managed.pk)
        self.assertEqual(file_object.lifecycle_status, MemoryFileObject.LifecycleStatus.MANAGED_ACTIVE)
        self.assertFalse(source_placement.is_current)
        self.assertEqual(source_placement.placement_status, MemoryFilePhysicalPlacement.PlacementStatus.MIGRATED)
        self.assertFalse(
            MemoryFilePhysicalPlacement.objects.filter(
                file_object=file_object,
                storage_backend=MemoryFilePhysicalPlacement.StorageBackend.SOURCE_FS,
                path_role=MemoryFilePhysicalPlacement.PathRole.SOURCE_CURRENT,
                is_current=True,
            ).exists()
        )

    def test_sync_repairs_partial_managed_activation_instead_of_restoring_source(self):
        source, file_object = self.create_scoped_file(
            source_code="filehub-sync-partial-managed",
            token=f"user:{self.actor.pk}",
        )
        source_object = file_object.current_version.source_object
        source_placement = file_object.current_physical_placement
        managed = MemoryFilePhysicalPlacement.objects.create(
            file_object=file_object,
            source_object=source_object,
            storage_backend=MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS,
            physical_ref="/managed/partial.txt",
            relative_path="managed/partial.txt",
            path_role=MemoryFilePhysicalPlacement.PathRole.MANAGED_CURRENT,
            placement_status=MemoryFilePhysicalPlacement.PlacementStatus.ACTIVE,
            is_current=True,
        )
        # Simulate a crash after managed placement activation but before the
        # object pointer/lifecycle update.
        self.assertEqual(file_object.current_physical_placement_id, source_placement.pk)
        self.assertEqual(file_object.lifecycle_status, MemoryFileObject.LifecycleStatus.SOURCE_ACTIVE)

        with self.settings(
            LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=_file_organization_profiles(
                source_code=source.code,
                managed_root=Path("/tmp/filehub-sync-partial-managed"),
            )
        ):
            sync_file_objects_from_source_objects(source=source)

        file_object.refresh_from_db()
        source_placement.refresh_from_db()
        self.assertEqual(file_object.current_physical_placement_id, managed.pk)
        self.assertEqual(file_object.lifecycle_status, MemoryFileObject.LifecycleStatus.MANAGED_ACTIVE)
        self.assertFalse(source_placement.is_current)
        self.assertEqual(source_placement.placement_status, MemoryFilePhysicalPlacement.PlacementStatus.MIGRATED)

    def test_move_execution_fences_source_disable_during_copy_and_quarantine(self):
        from .file_organization_move import execute_move_job

        for phase in ("copy", "quarantine"):
            with self.subTest(phase=phase), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir) / "source"
                managed_root = Path(tmpdir) / "managed"
                root.mkdir()
                managed_root.mkdir()
                path = root / f"{phase}.txt"
                path.write_text(f"disable during {phase}", encoding="utf-8")
                source, file_object = self.create_scoped_file(
                    source_code=f"filehub-disable-during-{phase}",
                    token=f"user:{self.actor.pk}",
                    relative_path=f"{phase}.txt",
                )
                source.config = {**source.config, "source_ref": str(root)}
                source.save(update_fields=["config", "updated_at"])
                source_object = file_object.current_version.source_object
                source_object.object_uri = str(path)
                source_object.content_hash = sha256_file(path)
                source_object.size_bytes = path.stat().st_size
                source_object.save(
                    update_fields=["object_uri", "content_hash", "size_bytes", "updated_at"]
                )
                version = file_object.current_version
                version.sha256 = source_object.content_hash
                version.size_bytes = source_object.size_bytes
                version.storage_ref = str(path)
                version.save(update_fields=["sha256", "size_bytes", "storage_ref", "updated_at"])
                placement = file_object.current_physical_placement
                placement.physical_ref = str(path)
                placement.save(update_fields=["physical_ref", "updated_at"])
                profiles = _file_organization_profiles(source_code=source.code, managed_root=managed_root)
                with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                    job = _create_system_planned_move_job(
                        file_object=file_object,
                        target_relative_path=f"managed/{phase}.txt",
                    )
                    job.expected_sha256 = version.sha256
                    job.expected_size_bytes = version.size_bytes
                    job.status = MemoryFileMoveJob.Status.APPROVED
                    job.save(
                        update_fields=[
                            "expected_sha256",
                            "expected_size_bytes",
                            "status",
                            "updated_at",
                        ]
                    )
                    _claimed, token = _claim_move_job(job.pk)

                    def disable_source():
                        MemorySource.objects.filter(pk=source.pk).update(
                            status=MemorySource.Status.DISABLED,
                            updated_at=timezone.now(),
                        )

                    fake_copy = SimpleNamespace(
                        storage_ref=str(managed_root / f"managed-{phase}.txt"),
                        relative_path=f"managed/{phase}.txt",
                        sha256=version.sha256,
                        size_bytes=version.size_bytes,
                    )
                    fake_quarantine = SimpleNamespace(
                        storage_ref=str(managed_root / f"quarantine-{phase}.txt"),
                        relative_path=f"quarantine/{phase}.txt",
                    )

                    def copy_side_effect(*_args, **_kwargs):
                        if phase == "copy":
                            disable_source()
                        return fake_copy

                    def quarantine_side_effect(*_args, **_kwargs):
                        disable_source()
                        return fake_quarantine

                    with patch(
                        "apps.filehub.file_organization_move.ManagedFSStorageBackend.copy_from_path",
                        side_effect=copy_side_effect,
                    ), patch(
                        "apps.filehub.file_organization_move.ManagedFSStorageBackend.quarantine_source",
                        side_effect=quarantine_side_effect,
                    ):
                        self.assertEqual(
                            execute_move_job(job_id=job.pk, claim_token=token),
                            "needs_review",
                        )
                    job.refresh_from_db()
                    self.assertEqual(job.status, MemoryFileMoveJob.Status.NEEDS_REVIEW)
                    self.assertIn("Источник отключен", job.error_message)

    def test_direct_execute_does_not_mutate_claimed_job_for_disabled_source(self):
        from .file_organization_move import execute_move_job

        source, file_object = self.create_scoped_file(
            source_code="filehub-disabled-before-execute",
            token=f"user:{self.actor.pk}",
        )
        with TemporaryDirectory() as tmpdir, self.settings(
            LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=_file_organization_profiles(
                source_code=source.code,
                managed_root=Path(tmpdir),
            )
        ):
            job = _create_system_planned_move_job(
                file_object=file_object,
                target_relative_path="managed/disabled.txt",
            )
        job.status = MemoryFileMoveJob.Status.COPY_STAGED
        job.started_at = timezone.now()
        job.manifest = {"claim_token": "disabled-token", "phase": "COPY_STAGED"}
        job.save(update_fields=["status", "started_at", "manifest", "updated_at"])
        before_manifest = dict(job.manifest)
        MemorySource.objects.filter(pk=source.pk).update(
            status=MemorySource.Status.DISABLED,
            updated_at=timezone.now(),
        )

        with self.assertRaises(ValueError):
            execute_move_job(job_id=job.pk, claim_token="disabled-token")
        job.refresh_from_db()
        self.assertEqual(job.status, MemoryFileMoveJob.Status.COPY_STAGED)
        self.assertEqual(job.manifest, before_manifest)

    def test_purge_recovers_committed_io_intent_after_unlink_crash(self):
        source, file_object = self.create_scoped_file(
            source_code="filehub-purge-recovery",
            token=f"user:{self.actor.pk}",
        )
        with TemporaryDirectory() as tmpdir:
            managed_root = Path(tmpdir) / "managed"
            managed_root.mkdir()
            missing_quarantine = managed_root / "quarantine" / "already-unlinked.txt"
            quarantine_placement = MemoryFilePhysicalPlacement.objects.create(
                file_object=file_object,
                source_object=file_object.current_version.source_object,
                storage_backend=MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS,
                physical_ref=str(missing_quarantine),
                relative_path="quarantine/already-unlinked.txt",
                path_role=MemoryFilePhysicalPlacement.PathRole.QUARANTINE,
                placement_status=MemoryFilePhysicalPlacement.PlacementStatus.QUARANTINED,
                is_current=False,
            )
            profiles = _file_organization_profiles(source_code=source.code, managed_root=managed_root)
            with self.settings(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES=profiles):
                job = _create_system_planned_move_job(
                    file_object=file_object,
                    target_relative_path="managed/recovery.txt",
                )
                job.status = MemoryFileMoveJob.Status.SOURCE_QUARANTINED
                job.retention_until = timezone.now() - timedelta(days=1)
                job.manifest = {
                    "phase": "PURGE_IO",
                    "purge_token": "recovery-token",
                    "quarantine_storage_ref": str(missing_quarantine),
                    "quarantine_sha256": job.expected_sha256,
                    "quarantine_size_bytes": job.expected_size_bytes,
                }
                job.save(update_fields=["status", "retention_until", "manifest", "updated_at"])
                result = purge_ready_source_files(source=source, backup_checkpoint_ref="checkpoint")

            self.assertEqual(result["purged"], 1)
            job.refresh_from_db()
            file_object.refresh_from_db()
            quarantine_placement.refresh_from_db()
            self.assertEqual(job.status, MemoryFileMoveJob.Status.SOURCE_PURGED)
            self.assertEqual(job.manifest["phase"], "SOURCE_PURGED")
            self.assertEqual(file_object.lifecycle_status, MemoryFileObject.LifecycleStatus.SOURCE_PURGED)
            self.assertEqual(quarantine_placement.path_role, MemoryFilePhysicalPlacement.PathRole.PURGED)

    def test_usage_event_rejects_disabled_source_without_file_or_view(self):
        source, _file_object = self.create_scoped_file(
            source_code="filehub-disabled-event",
            token=f"user:{self.actor.pk}",
        )
        source.status = MemorySource.Status.DISABLED
        source.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValueError):
            record_file_usage_event(
                source=source,
                event_kind=MemoryFileUsageEvent.EventKind.FILE_OPENED,
                actor=self.actor,
            )

    def test_disabled_source_is_fail_closed_even_for_superuser_file_reads(self):
        source, file_object = self.create_scoped_file(
            source_code="filehub-disabled-read",
            token=f"user:{self.actor.pk}",
        )
        root = User.objects.create_superuser(username="filehub-disabled-root", password="pass")
        source.status = MemorySource.Status.DISABLED
        source.save(update_fields=["status", "updated_at"])
        file_object.refresh_from_db()
        self.assertFalse(can_access_file_object(root, file_object))
        self.assertEqual(list(visible_file_objects(root, source=source)), [])
        self.assertEqual(list(visible_file_objects(root)), [])

    def test_stale_loaded_source_is_rechecked_after_concurrent_disable(self):
        source, file_object = self.create_scoped_file(
            source_code="filehub-stale-disabled-read",
            token=f"user:{self.actor.pk}",
        )
        stale_source = MemorySource.objects.get(pk=source.pk)
        stale_file = MemoryFileObject.objects.select_related(
            "source", "current_version", "current_version__source_object"
        ).get(pk=file_object.pk)
        MemorySource.objects.filter(pk=source.pk).update(
            status=MemorySource.Status.DISABLED,
            updated_at=timezone.now(),
        )

        self.assertEqual(stale_source.status, MemorySource.Status.ENABLED)
        self.assertFalse(can_access_source_for_organization(self.actor, stale_source))
        self.assertFalse(can_access_file_object(self.actor, stale_file))
        self.assertEqual(list(visible_file_objects(self.actor, source=stale_source)), [])

    def test_public_filehub_writers_use_the_common_exclusive_lock(self):
        source = self.create_source(code="filehub-lock-boundary")
        with patch(
            "apps.filehub.file_organization_baseline._build_baseline_virtual_structure_locked",
            return_value={"ok": True},
        ), patch("apps.filehub.file_organization_baseline.exclusive_file_lock") as baseline_lock:
            baseline_lock.return_value.__enter__.return_value = None
            self.assertEqual(build_baseline_virtual_structure(source=source, dry_run=True), {"ok": True})
            baseline_lock.assert_called_once()
        with patch(
            "apps.filehub.file_organization_incoming._process_incoming_folder_locked",
            return_value={"ok": True},
        ), patch("apps.filehub.file_organization_incoming.exclusive_file_lock") as incoming_lock:
            incoming_lock.return_value.__enter__.return_value = None
            self.assertEqual(process_incoming_folder(source=source, dry_run=True), {"ok": True})
            incoming_lock.assert_called_once()
        with patch(
            "apps.filehub.file_organization_stats._build_organization_proposals_locked",
            return_value={"ok": True},
        ), patch("apps.filehub.file_organization_stats.exclusive_file_lock") as stats_lock:
            stats_lock.return_value.__enter__.return_value = None
            self.assertEqual(build_organization_proposals(source=source, dry_run=True), {"ok": True})
            stats_lock.assert_called_once()
