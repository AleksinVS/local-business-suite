import os
import uuid
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.filehub.file_organization_baseline import build_baseline_virtual_structure
from apps.filehub.file_organization_incoming import process_incoming_folder
from apps.filehub.file_organization_move import purge_ready_source_files, run_move_worker
from apps.filehub.file_organization_stats import (
    apply_organization_proposal_decision,
    build_organization_proposals,
    record_file_usage_event,
)
from apps.filehub.models import (
    MemoryFileMoveJob,
    MemoryFileOrganizationProposal,
    MemoryFileUsageEvent,
    MemoryFileVirtualPlacement,
)
from apps.memory.document_ingestion import discover_source_objects
from apps.memory.config_documents import get_memory_document_snapshots
from apps.memory.models import MemorySearchDocument, MemorySource, MemorySourceObject
from apps.memory.policies import can_access_search_document


class Command(BaseCommand):
    help = "Run an end-to-end check of file source auto organization."

    def handle(self, *args, **options):
        User = get_user_model()
        marker = uuid.uuid4().hex[:12]
        workspace = Path(".local") / "e2e" / "memory_file_auto_organization" / marker
        source_root = workspace / "source"
        managed_root = workspace / "managed"
        incoming = source_root / "incoming" / "new"
        incoming.mkdir(parents=True, exist_ok=True)
        managed_root.mkdir(parents=True, exist_ok=True)
        source_file = source_root / "contracts" / "dogovor-2026-alpha.txt"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("Договор 2026 с поставщиком alpha. Контрольный маркер auto-org.", encoding="utf-8")
        incoming_file = incoming / "akt-2026-beta.txt"
        incoming_file.write_text("Акт 2026 по поставке beta. Контрольный маркер incoming.", encoding="utf-8")
        old_timestamp = timezone.now().timestamp() - 60
        os.utime(source_file, (old_timestamp, old_timestamp))
        os.utime(incoming_file, (old_timestamp, old_timestamp))

        group, _created = Group.objects.get_or_create(name=f"docs-readers-{marker}")
        admin = User.objects.create_user(username=f"auto-org-admin-{marker}", password="pass", is_staff=True)
        admin_role, _ = Group.objects.get_or_create(name="admin")
        memory_admin, _ = Group.objects.get_or_create(name="memory_admin")
        admin.groups.add(group, admin_role, memory_admin)
        reader = User.objects.create_user(username=f"auto-org-reader-{marker}", password="pass")
        reader.groups.add(group)
        outsider = User.objects.create_user(username=f"auto-org-outsider-{marker}", password="pass")
        source_item = {
            "code": f"auto_org_e2e_{marker}",
            "title": "Auto organization e2e",
            "source_kind": "local_path",
            "domain": "docs",
            "owner": "engineering",
            "description": "Explicitly scoped permanent FileHub e2e source.",
            "enabled": True,
            "sync_mode": "manual",
            "schedule": None,
            "source_ref": str(source_root),
            "scope_rule": "authenticated_user",
            "sensitivity": "internal",
            "pii_policy": "no_pii_expected",
            "versioning_mode": "snapshot_only",
            "retention_policy": "default_internal",
            "trust_status": "review_required",
            "authority_class": "candidate_input",
            "trusted_for_context": False,
            "requires_source_review": True,
            "review_owner": "knowledge_owner",
            "trusted_context_kinds": ["citation"],
            "untrusted_handling": "review_required",
            "extractor_profile": "project_docs_v1",
            "chunking_profile": "long_policy_doc_v1",
            "index_profiles": ["fulltext_default"],
            "ignore_patterns": ["incoming/**"],
            "ingestion_profile": "corporate_docs_windows_v1",
            "file_organization_profile": "auto_org_e2e_v1",
            "default_acl": {"allow": [{"kind": "group", "name": group.name}]},
        }
        # The source projection and its operation snapshot are deliberately
        # local to this e2e invocation. No settings holder is used, and the
        # production path remains fail-closed for an unlisted source.
        source = MemorySource.objects.create(
            code=source_item["code"],
            title=source_item["title"],
            source_kind=source_item["source_kind"],
            domain=source_item["domain"],
            owner=source_item["owner"],
            status=MemorySource.Status.ENABLED,
            trust_status=source_item["trust_status"],
            authority_class=source_item["authority_class"],
            trusted_for_context=source_item["trusted_for_context"],
            requires_source_review=source_item["requires_source_review"],
            review_owner=source_item["review_owner"],
            trusted_context_kinds=source_item["trusted_context_kinds"],
            untrusted_handling=source_item["untrusted_handling"],
            sync_mode=source_item["sync_mode"],
            scope_rule=source_item["scope_rule"],
            sensitivity=source_item["sensitivity"],
            pii_policy=source_item["pii_policy"],
            extractor_profile=source_item["extractor_profile"],
            chunking_profile=source_item["chunking_profile"],
            index_profiles=source_item["index_profiles"],
            config=source_item,
        )
        profiles = {
            "version": "1.0",
            "name": "memory_file_organization_profiles",
            "description": "E2E file organization profile.",
            "profiles": {
                "auto_org_e2e_v1": {
                    "enabled": True,
                    "source_code": source.code,
                    "incoming_path": "incoming/new",
                    "managed_root": str(managed_root),
                    "baseline_profile": "baseline_auto_v1",
                    "physical_move_policy": "approval_required",
                    "source_delete_policy": {
                        "mode": "quarantine_then_purge",
                        "retention_days": 30,
                        "requires_backup_checkpoint": True,
                    },
                    "storage_backend": "managed_fs",
                    "future_backends": ["s3_compatible"],
                    "proposal_thresholds": {
                        "min_users": 2,
                        "min_events": 2,
                        "min_files": 1,
                        "min_confidence": 0.2,
                    },
                }
            },
        }
        base_snapshots = get_memory_document_snapshots(
            document_ids=(
                "memory.contract.sources",
                "memory.contract.ingestion_profiles",
            )
        )
        source_contract = replace(
            base_snapshots["memory.contract.sources"],
            payload=[*deepcopy(base_snapshots["memory.contract.sources"].payload), source_item],
        )
        organization_snapshot = replace(
            base_snapshots["memory.contract.ingestion_profiles"],
            document_id="memory.contract.file_organization_profiles",
            payload=profiles,
        )
        scoped_snapshots = {
            "memory.contract.sources": source_contract,
            "memory.contract.ingestion_profiles": base_snapshots["memory.contract.ingestion_profiles"],
            "memory.contract.file_organization_profiles": organization_snapshot,
        }
        discovery = discover_source_objects(
            source=source, dry_run=False, snapshots=scoped_snapshots
        )
        baseline = build_baseline_virtual_structure(
            source=source, dry_run=False, snapshots=scoped_snapshots
        )
        if baseline["placements"] < 1 or not source_file.exists():
            raise CommandError("Baseline did not create placements or changed physical files.")
        incoming_metrics = process_incoming_folder(
            source=source, dry_run=False, snapshots=scoped_snapshots
        )
        if incoming_metrics["placements"] < 1:
            raise CommandError("Incoming worker did not create virtual placement.")
        source_object = MemorySourceObject.objects.get(source=source, relative_path="contracts/dogovor-2026-alpha.txt")
        source_object.metadata = {**(source_object.metadata or {}), "scope_tokens": [f"group:{group.name}"]}
        source_object.save(update_fields=["metadata", "updated_at"])
        file_object = source_object.file_versions.first().file_object
        document = MemorySearchDocument.objects.create(
            document_id=f"source:auto-org-e2e:{marker}",
            corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA,
            object_kind=MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
            source_object=source_object,
            body_hash="body-hash",
            index_status=MemorySearchDocument.IndexStatus.READY,
            metadata={"scope_tokens": [f"group:{group.name}"]},
        )
        if not can_access_search_document(
            reader, document, snapshots=scoped_snapshots
        ) or can_access_search_document(outsider, document, snapshots=scoped_snapshots):
            raise CommandError("Virtual view access control check failed.")
        placement = MemoryFileVirtualPlacement.objects.filter(file_object=file_object).first()
        for actor in (admin, reader):
            record_file_usage_event(
                source=source,
                event_kind=MemoryFileUsageEvent.EventKind.BASELINE_ACCEPTED,
                file_object=file_object,
                view=placement.view,
                actor=actor,
                virtual_path=placement.virtual_path,
            )
        proposal_metrics = build_organization_proposals(
            source=source, dry_run=False, snapshots=scoped_snapshots
        )
        if proposal_metrics["proposals"] < 1:
            raise CommandError("Usage statistics did not create an organization proposal.")
        proposal = MemoryFileOrganizationProposal.objects.filter(source=source).first()
        # The physical approval and exact job set use the same
        # actor-aware command as the HTTP endpoint.
        proposal.metadata = {**(proposal.metadata or {}), "file_ids": [file_object.file_id]}
        proposal.save(update_fields=["metadata", "updated_at"])
        apply_organization_proposal_decision(
            proposal=proposal,
            actor=admin,
            decision="accept_for_physical_move",
            create_jobs=True,
            snapshots=scoped_snapshots,
        )
        job = MemoryFileMoveJob.objects.get(proposal=proposal)
        move_metrics = run_move_worker(source=source, snapshots=scoped_snapshots)
        job.refresh_from_db()
        if move_metrics["moved"] != 1 or job.status != MemoryFileMoveJob.Status.SOURCE_QUARANTINED:
            raise CommandError("Approved managed_fs move did not finish safely.")
        if source_file.exists():
            raise CommandError("Source file was not moved into quarantine after verified managed copy.")
        job.retention_until = timezone.now() - timedelta(days=1)
        job.save(update_fields=["retention_until", "updated_at"])
        purge_blocked = purge_ready_source_files(
            source=source,
            backup_checkpoint_ref="",
            dry_run=False,
            snapshots=scoped_snapshots,
        )
        if purge_blocked["blocked"] < 1:
            raise CommandError("Purge was not blocked without backup checkpoint.")

        self.stdout.write(
            self.style.SUCCESS(
                "Memory file auto organization e2e succeeded: "
                f"source={source.code}, discovery_seen={discovery['seen']}, "
                f"baseline_placements={baseline['placements']}, move_job={job.idempotency_key}"
            )
        )
