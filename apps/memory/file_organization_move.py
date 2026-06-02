from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from .document_ingestion import sha256_file
from .file_organization import get_file_organization_profile, normalize_relative_path, sanitize_path_segment
from .models import (
    MemoryFileMoveJob,
    MemoryFileObject,
    MemoryFileOrganizationProposal,
    MemoryFilePhysicalPlacement,
    MemorySource,
)
from .storage_backends import ManagedFSStorageBackend


def create_move_job_for_file(
    *,
    file_object: MemoryFileObject,
    target_relative_path: str,
    proposal: MemoryFileOrganizationProposal | None = None,
    approved_by=None,
) -> MemoryFileMoveJob:
    version = file_object.current_version
    if version is None or not version.sha256:
        raise ValueError("File object has no current version with SHA-256.")
    source_placement = _current_source_placement(file_object)
    if source_placement is None:
        raise ValueError("File object has no current source placement.")
    target_relative_path = normalize_relative_path(target_relative_path)
    idempotency_key = _move_idempotency_key(
        source_code=file_object.source.code,
        file_id=file_object.file_id,
        target_relative_path=target_relative_path,
        expected_sha256=version.sha256,
    )
    status = MemoryFileMoveJob.Status.APPROVED if approved_by is not None else MemoryFileMoveJob.Status.PLANNED
    job, _created = MemoryFileMoveJob.objects.update_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "source": file_object.source,
            "file_object": file_object,
            "proposal": proposal,
            "source_placement": source_placement,
            "status": status,
            "target_storage_backend": MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS,
            "target_relative_path": target_relative_path,
            "expected_sha256": version.sha256,
            "expected_size_bytes": version.size_bytes,
            "approved_by": approved_by,
            "approved_at": timezone.now() if approved_by is not None else None,
        },
    )
    return job


def create_move_jobs_for_accepted_proposal(*, proposal: MemoryFileOrganizationProposal, approved_by) -> dict:
    if proposal.status != MemoryFileOrganizationProposal.Status.ACCEPTED_PHYSICAL:
        raise ValueError("Move jobs can be created only for accepted physical proposals.")
    file_ids = (proposal.metadata or {}).get("file_ids") or []
    file_queryset = MemoryFileObject.objects.filter(source=proposal.source)
    if file_ids:
        file_queryset = file_queryset.filter(file_id__in=file_ids)
    metrics = {"planned": 0, "skipped": 0}
    for file_object in file_queryset.select_related("current_version", "source"):
        target = _target_path_for_file(proposal=proposal, file_object=file_object)
        try:
            create_move_job_for_file(file_object=file_object, target_relative_path=target, proposal=proposal, approved_by=approved_by)
        except ValueError:
            metrics["skipped"] += 1
            continue
        metrics["planned"] += 1
    return metrics


def run_move_worker(
    *,
    source: MemorySource,
    dry_run: bool = False,
    limit: int | None = None,
    require_enabled: bool = True,
) -> dict:
    profile = get_file_organization_profile(source, require_enabled=require_enabled)
    queryset = MemoryFileMoveJob.objects.select_related("file_object", "source_placement").filter(
        source=source,
        status=MemoryFileMoveJob.Status.APPROVED,
    ).order_by("created_at", "id")
    if limit:
        queryset = queryset[:limit]
    metrics = {"eligible": 0, "moved": 0, "failed": 0, "needs_review": 0, "dry_run": dry_run}
    for job in queryset:
        metrics["eligible"] += 1
        if dry_run:
            continue
        result = execute_move_job(job=job, profile=profile)
        metrics[result] += 1
    return metrics


def execute_move_job(*, job: MemoryFileMoveJob, profile=None) -> str:
    profile = profile or get_file_organization_profile(job.source)
    if profile.physical_move_policy == "disabled":
        return _mark_job_needs_review(job, "Physical move policy is disabled.")
    job.attempts += 1
    job.started_at = job.started_at or timezone.now()
    job.status = MemoryFileMoveJob.Status.COPY_STAGED
    job.save(update_fields=["attempts", "started_at", "status", "updated_at"])
    try:
        source_placement = job.source_placement or _current_source_placement(job.file_object)
        if source_placement is None:
            return _mark_job_needs_review(job, "Source placement is missing.")
        source_path = Path(source_placement.physical_ref)
        if not source_path.exists():
            return _mark_job_needs_review(job, "Source file is missing before managed copy.")
        if source_path.stat().st_size != job.expected_size_bytes or sha256_file(source_path) != job.expected_sha256:
            return _mark_job_needs_review(job, "Source file changed before managed copy.")

        backend = ManagedFSStorageBackend(profile.managed_root_path)
        copy_result = backend.copy_from_path(
            source_path,
            target_relative_path=job.target_relative_path,
            expected_hash=job.expected_sha256,
            expected_size=job.expected_size_bytes,
        )
        job.status = MemoryFileMoveJob.Status.VERIFIED
        job.target_storage_ref = copy_result.storage_ref
        job.manifest = {
            **(job.manifest or {}),
            "managed_storage_ref": copy_result.storage_ref,
            "managed_relative_path": copy_result.relative_path,
            "verified_sha256": copy_result.sha256,
            "verified_size_bytes": copy_result.size_bytes,
            "verified_at": timezone.now().isoformat(),
        }
        job.save(update_fields=["status", "target_storage_ref", "manifest", "updated_at"])

        managed_placement, _created = MemoryFilePhysicalPlacement.objects.update_or_create(
            file_object=job.file_object,
            storage_backend=MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS,
            physical_ref=copy_result.storage_ref,
            path_role=MemoryFilePhysicalPlacement.PathRole.MANAGED_CURRENT,
            defaults={
                "source_object": source_placement.source_object,
                "relative_path": copy_result.relative_path,
                "placement_status": MemoryFilePhysicalPlacement.PlacementStatus.ACTIVE,
                "is_current": True,
                "metadata": {"move_job_id": job.id, "expected_sha256": job.expected_sha256},
            },
        )
        MemoryFilePhysicalPlacement.objects.filter(file_object=job.file_object).exclude(id=managed_placement.id).update(is_current=False)
        source_placement.placement_status = MemoryFilePhysicalPlacement.PlacementStatus.MIGRATED
        source_placement.is_current = False
        source_placement.save(update_fields=["placement_status", "is_current", "updated_at"])
        job.file_object.current_physical_placement = managed_placement
        job.file_object.lifecycle_status = MemoryFileObject.LifecycleStatus.MANAGED_ACTIVE
        job.file_object.save(update_fields=["current_physical_placement", "lifecycle_status", "updated_at"])
        job.status = MemoryFileMoveJob.Status.MANAGED_ACTIVE
        job.save(update_fields=["status", "updated_at"])

        if profile.source_delete_policy.mode == "disabled":
            job.finished_at = timezone.now()
            job.save(update_fields=["finished_at", "updated_at"])
            return "moved"

        quarantine_result = backend.quarantine_source(
            source_path,
            quarantine_relative_path=_quarantine_relative_path(job=job, source_path=source_path),
        )
        MemoryFilePhysicalPlacement.objects.update_or_create(
            file_object=job.file_object,
            storage_backend=MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS,
            physical_ref=quarantine_result.storage_ref,
            path_role=MemoryFilePhysicalPlacement.PathRole.QUARANTINE,
            defaults={
                "source_object": source_placement.source_object,
                "relative_path": quarantine_result.relative_path,
                "placement_status": MemoryFilePhysicalPlacement.PlacementStatus.QUARANTINED,
                "is_current": False,
                "metadata": {"move_job_id": job.id, "source_relative_path": source_placement.relative_path},
            },
        )
        job.status = MemoryFileMoveJob.Status.SOURCE_QUARANTINED
        job.retention_until = timezone.now() + timedelta(days=profile.source_delete_policy.retention_days)
        job.finished_at = timezone.now()
        job.manifest = {
            **(job.manifest or {}),
            "quarantine_storage_ref": quarantine_result.storage_ref,
            "quarantine_relative_path": quarantine_result.relative_path,
            "source_relative_path": source_placement.relative_path,
        }
        job.file_object.lifecycle_status = MemoryFileObject.LifecycleStatus.SOURCE_QUARANTINED
        job.file_object.save(update_fields=["lifecycle_status", "updated_at"])
        job.save(update_fields=["status", "retention_until", "finished_at", "manifest", "updated_at"])
        return "moved"
    except Exception as exc:
        job.status = MemoryFileMoveJob.Status.FAILED
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        return "failed"


def purge_ready_source_files(
    *,
    source: MemorySource,
    backup_checkpoint_ref: str = "",
    dry_run: bool = False,
    require_enabled: bool = True,
) -> dict:
    profile = get_file_organization_profile(source, require_enabled=require_enabled)
    now = timezone.now()
    queryset = MemoryFileMoveJob.objects.select_related("file_object").filter(
        source=source,
        status=MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
        retention_until__lte=now,
    )
    metrics = {"eligible": queryset.count(), "purged": 0, "blocked": 0, "dry_run": dry_run}
    if profile.source_delete_policy.mode != "quarantine_then_purge":
        metrics["blocked"] = metrics["eligible"]
        return metrics
    if profile.source_delete_policy.requires_backup_checkpoint and not backup_checkpoint_ref:
        metrics["blocked"] = metrics["eligible"]
        return metrics
    backend = ManagedFSStorageBackend(profile.managed_root_path)
    for job in queryset:
        quarantine_ref = (job.manifest or {}).get("quarantine_storage_ref", "")
        if not quarantine_ref:
            metrics["blocked"] += 1
            continue
        if dry_run:
            metrics["purged"] += 1
            continue
        backend.purge(quarantine_ref)
        MemoryFilePhysicalPlacement.objects.filter(
            file_object=job.file_object,
            physical_ref=quarantine_ref,
            path_role=MemoryFilePhysicalPlacement.PathRole.QUARANTINE,
        ).update(
            placement_status=MemoryFilePhysicalPlacement.PlacementStatus.PURGED,
            path_role=MemoryFilePhysicalPlacement.PathRole.PURGED,
            is_current=False,
            updated_at=timezone.now(),
        )
        job.status = MemoryFileMoveJob.Status.SOURCE_PURGED
        job.backup_checkpoint_ref = backup_checkpoint_ref
        job.file_object.lifecycle_status = MemoryFileObject.LifecycleStatus.SOURCE_PURGED
        job.file_object.save(update_fields=["lifecycle_status", "updated_at"])
        job.save(update_fields=["status", "backup_checkpoint_ref", "updated_at"])
        metrics["purged"] += 1
    return metrics


def _mark_job_needs_review(job: MemoryFileMoveJob, message: str) -> str:
    job.status = MemoryFileMoveJob.Status.NEEDS_REVIEW
    job.error_message = message
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
    return "needs_review"


def _current_source_placement(file_object: MemoryFileObject) -> MemoryFilePhysicalPlacement | None:
    return (
        MemoryFilePhysicalPlacement.objects.filter(
            file_object=file_object,
            storage_backend=MemoryFilePhysicalPlacement.StorageBackend.SOURCE_FS,
            path_role=MemoryFilePhysicalPlacement.PathRole.SOURCE_CURRENT,
            placement_status=MemoryFilePhysicalPlacement.PlacementStatus.ACTIVE,
        )
        .order_by("-is_current", "-updated_at", "-id")
        .first()
    )


def _move_idempotency_key(*, source_code: str, file_id: str, target_relative_path: str, expected_sha256: str) -> str:
    basis = f"{source_code}:{file_id}:{target_relative_path}:{expected_sha256}"
    return "file-move:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:40]


def _target_path_for_file(*, proposal: MemoryFileOrganizationProposal, file_object: MemoryFileObject) -> str:
    placement = (
        file_object.virtual_placements.filter(status__in=["accepted", "proposed"])
        .order_by("-confidence", "-updated_at")
        .first()
    )
    file_name = "file"
    if file_object.current_physical_placement and file_object.current_physical_placement.relative_path:
        file_name = Path(file_object.current_physical_placement.relative_path).name
    bucket = sanitize_path_segment((proposal.proposed_rule or {}).get("bucket") or "managed", fallback="managed")
    if placement is not None:
        file_name = Path(placement.virtual_path).name or file_name
    return normalize_relative_path(f"by-function/{bucket}/{file_object.file_id}/{sanitize_path_segment(file_name, fallback='file')}")


def _quarantine_relative_path(*, job: MemoryFileMoveJob, source_path: Path) -> str:
    file_name = sanitize_path_segment(source_path.name, fallback="file")
    return normalize_relative_path(f"quarantine/{job.file_object.file_id}/{file_name}")
