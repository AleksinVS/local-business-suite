from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from apps.core.file_locks import access_control_write_lock_path, exclusive_file_lock
from apps.memory.document_ingestion import sha256_file
from apps.memory.models import MemorySource, MemorySourceObject
from apps.memory.policies import can_review_organization_memory, can_view_memory_review_queue, is_active_actor
from apps.memory.storage_backends import ManagedFSStorageBackend

from .file_organization import (
    get_file_organization_profile,
    normalize_relative_path,
    require_enabled_file_source,
    sanitize_path_segment,
)
from .models import (
    MemoryFileMoveJob,
    MemoryFileObject,
    MemoryFileOrganizationProposal,
    MemoryFileOrganizationDecision,
    MemoryFileObjectVersion,
    MemoryFilePhysicalPlacement,
)
from .selectors import can_access_file_object, can_access_source_for_organization


# Canonical database lock order for actor-aware file operations:
# actor -> source -> proposal -> files (id) -> jobs (id) -> placements.


@transaction.atomic
def _create_system_planned_move_job(
    *,
    file_object: MemoryFileObject,
    target_relative_path: str,
    proposal: MemoryFileOrganizationProposal | None = None,
) -> MemoryFileMoveJob:
    """Explicit bootstrap API: create only a PLANNED job."""
    return _create_move_job_for_file(
        file_object=file_object,
        target_relative_path=target_relative_path,
        proposal=proposal,
        approved_by=None,
        approve=False,
    )


def _create_approved_move_job_for_file(
    *,
    file_object: MemoryFileObject,
    target_relative_path: str,
    proposal: MemoryFileOrganizationProposal,
    approved_by,
) -> MemoryFileMoveJob:
    return _create_move_job_for_file(
        file_object=file_object,
        target_relative_path=target_relative_path,
        proposal=proposal,
        approved_by=approved_by,
        approve=True,
    )


def _create_move_job_for_file(
    *,
    file_object: MemoryFileObject,
    target_relative_path: str,
    proposal: MemoryFileOrganizationProposal | None,
    approved_by,
    approve: bool,
) -> MemoryFileMoveJob:
    source = MemorySource.objects.select_for_update().get(pk=file_object.source_id)
    file_object = (
        MemoryFileObject.objects.select_for_update()
        .select_related("source", "current_version", "current_physical_placement")
        .get(pk=file_object.pk)
    )
    if file_object.source_id != source.pk:
        raise ValidationError("Источник файла изменился во время блокировки.")
    profile = get_file_organization_profile(file_object.source)
    if profile.storage_backend != MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS:
        raise ValidationError("Физический перенос поддерживает только managed_fs.")
    version = file_object.current_version
    if version is None or not version.sha256:
        raise ValueError("File object has no current version with SHA-256.")
    source_placement = _current_source_placement(file_object)
    if source_placement is None:
        raise ValueError("File object has no current source placement.")
    target_relative_path = normalize_relative_path(target_relative_path)
    if not approve:
        _assert_no_conflicting_move_job(
            file_object=file_object,
            proposal=proposal,
            target_relative_path=target_relative_path,
        )
    idempotency_key = _move_idempotency_key(
        source_code=file_object.source.code,
        file_id=file_object.file_id,
        target_relative_path=target_relative_path,
        expected_sha256=version.sha256,
    )
    job = MemoryFileMoveJob.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
    source_placement = (
        MemoryFilePhysicalPlacement.objects.select_for_update()
        .filter(
            pk=source_placement.pk,
            file_object=file_object,
            source_object__source_id=source.pk,
            is_current=True,
            placement_status=MemoryFilePhysicalPlacement.PlacementStatus.ACTIVE,
            path_role=MemoryFilePhysicalPlacement.PathRole.SOURCE_CURRENT,
        )
        .first()
    )
    if source_placement is None:
        raise ValidationError("Текущее размещение файла изменилось во время блокировки.")
    if job is not None:
        immutable = (
            job.source_id == file_object.source_id
            and job.file_object_id == file_object.pk
            and job.proposal_id == getattr(proposal, "pk", None)
            and job.source_placement_id == source_placement.pk
            and job.target_relative_path == target_relative_path
            and job.expected_sha256 == version.sha256
            and job.expected_size_bytes == version.size_bytes
        )
        if not immutable:
            raise ValidationError("Идемпотентный ключ уже связан с другим заданием переноса.")
        if (job.manifest or {}).get("profile_id") != profile.profile_id:
            raise ValidationError("Профиль задания изменился после его создания.")
        if job.status in {
            MemoryFileMoveJob.Status.COPY_STAGED,
            MemoryFileMoveJob.Status.VERIFIED,
            MemoryFileMoveJob.Status.MANAGED_ACTIVE,
            MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
            MemoryFileMoveJob.Status.SOURCE_PURGED,
            MemoryFileMoveJob.Status.NEEDS_REVIEW,
            MemoryFileMoveJob.Status.FAILED,
        }:
            if approve:
                raise ValidationError("Завершенное или выполняющееся задание нельзя повторно согласовать.")
            return job
        if approve and job.status == MemoryFileMoveJob.Status.PLANNED:
            job.status = MemoryFileMoveJob.Status.APPROVED
            job.approved_by = approved_by
            job.approved_at = timezone.now()
            job.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        return job
    status = MemoryFileMoveJob.Status.APPROVED if approve else MemoryFileMoveJob.Status.PLANNED
    return MemoryFileMoveJob.objects.create(
        idempotency_key=idempotency_key,
        source=file_object.source,
        file_object=file_object,
        proposal=proposal,
        source_placement=source_placement,
        status=status,
        target_storage_backend=MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS,
        target_relative_path=target_relative_path,
        expected_sha256=version.sha256,
        expected_size_bytes=version.size_bytes,
        approved_by=approved_by if approve else None,
        approved_at=timezone.now() if approve else None,
        manifest={"profile_id": profile.profile_id, "profile_source_code": profile.source_code},
    )


def create_move_jobs_for_accepted_proposal(*, proposal: MemoryFileOrganizationProposal, approved_by) -> dict:
    with exclusive_file_lock(access_control_write_lock_path(), timeout=300.0):
        with transaction.atomic():
            return _create_move_jobs_for_accepted_proposal_locked(
                proposal=proposal,
                approved_by=approved_by,
            )


def _create_move_jobs_for_accepted_proposal_locked(*, proposal: MemoryFileOrganizationProposal, approved_by) -> dict:
    """Create the complete, exact job set for one approved proposal.

    Missing, foreign, stale, or unauthorized membership rejects the whole
    operation.  There is intentionally no source-wide fallback.
    """
    approved_by = _lock_active_actor(approved_by)
    if not can_view_memory_review_queue(approved_by) or not can_review_organization_memory(approved_by):
        raise PermissionDenied("Недостаточно полномочий для физического переноса файлов.")
    proposal_ref = MemoryFileOrganizationProposal.objects.filter(pk=proposal.pk).values("source_id").first()
    if proposal_ref is None:
        raise ValidationError("Предложение файловой структуры больше не существует.")
    source = MemorySource.objects.select_for_update().get(pk=proposal_ref["source_id"])
    proposal = (
        MemoryFileOrganizationProposal.objects.select_for_update()
        .filter(pk=proposal.pk, source_id=source.pk)
        .first()
    )
    if proposal is None or proposal.source_id != source.pk:
        raise ValidationError("Источник предложения изменился во время блокировки.")
    proposal.source = source
    if not can_access_source_for_organization(approved_by, proposal.source):
        raise PermissionDenied("Источник файлов находится вне текущей области доступа.")
    if proposal.status != MemoryFileOrganizationProposal.Status.ACCEPTED_PHYSICAL:
        raise ValueError("Move jobs can be created only for accepted physical proposals.")
    raw_file_ids = (proposal.metadata or {}).get("file_ids")
    if not isinstance(raw_file_ids, list):
        raise ValidationError("У предложения отсутствует точный список файлов.")
    file_ids = [str(file_id).strip() for file_id in raw_file_ids if str(file_id).strip()]
    if not file_ids or len(set(file_ids)) != len(file_ids):
        raise ValidationError("Точный список файлов предложения пуст или содержит дубликаты.")
    file_ids = sorted(file_ids)
    if proposal.affected_file_count != len(file_ids):
        raise ValidationError("Количество файлов предложения не совпадает с точным списком.")
    expected_fingerprint = _membership_fingerprint(
        source=proposal.source,
        bucket=(proposal.proposed_rule or {}).get("bucket") or "",
        file_ids=file_ids,
    )
    if (proposal.metadata or {}).get("membership_fingerprint") != expected_fingerprint:
        raise ValidationError("Состав файлов предложения устарел или не имеет контрольного отпечатка.")
    file_queryset = MemoryFileObject.objects.filter(source=proposal.source, file_id__in=file_ids)
    files = list(
        file_queryset.select_for_update()
        .select_related("current_version", "source", "current_physical_placement")
        .order_by("id")
    )
    if {file.file_id for file in files} != set(file_ids) or len(files) != len(file_ids):
        raise ValidationError("Список файлов предложения содержит отсутствующий или чужой файл.")
    approved_decision = (
        MemoryFileOrganizationDecision.objects.filter(
            proposal=proposal,
            decision=MemoryFileOrganizationDecision.Decision.ACCEPT_FOR_PHYSICAL_MOVE,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    snapshot = (approved_decision.safe_metadata or {}).get("approved_snapshot") if approved_decision else None
    if not isinstance(snapshot, dict):
        raise ValidationError("У физического решения отсутствует immutable approved snapshot.")
    if (
        snapshot.get("source_id") != proposal.source_id
        or snapshot.get("source_code") != proposal.source.code
        or snapshot.get("bucket") != (proposal.proposed_rule or {}).get("bucket", "")
        or snapshot.get("file_ids") != file_ids
        or snapshot.get("membership_fingerprint") != (proposal.metadata or {}).get("membership_fingerprint")
    ):
        raise ValidationError("Снимок согласованного состава файлов изменен.")
    snapshot_objects = {item.get("file_id"): item for item in snapshot.get("objects", []) if isinstance(item, dict)}
    if set(snapshot_objects) != set(file_ids):
        raise ValidationError("Снимок согласованного состава файлов неполон.")
    for file_object in files:
        item = snapshot_objects[file_object.file_id]
        version = file_object.current_version
        placement = file_object.current_physical_placement
        if (
            item.get("file_object_id") != file_object.pk
            or item.get("version_id") != getattr(version, "pk", None)
            or item.get("sha256") != getattr(version, "sha256", None)
            or item.get("size_bytes") != getattr(version, "size_bytes", None)
            or item.get("source_placement_id") != getattr(placement, "pk", None)
        ):
            raise ValidationError("Текущая версия файла не совпадает с immutable approved snapshot.")
    if any(not can_access_file_object(approved_by, file_object) for file_object in files):
        raise PermissionDenied("Один из файлов находится вне текущей области доступа.")
    metrics = {"planned": 0, "skipped": 0}
    for file_object in files:
        target = _target_path_for_file(proposal=proposal, file_object=file_object)
        _assert_no_conflicting_move_job(file_object=file_object, proposal=proposal, target_relative_path=target)
        _create_approved_move_job_for_file(
            file_object=file_object,
            target_relative_path=target,
            proposal=proposal,
            approved_by=approved_by,
        )
        metrics["planned"] += 1
    if metrics["planned"] != len(file_ids):
        raise ValidationError("Не удалось создать полный набор заданий переноса.")
    return metrics


def _assert_no_conflicting_move_job(*, file_object, proposal, target_relative_path: str) -> None:
    unresolved = {
        MemoryFileMoveJob.Status.PLANNED,
        MemoryFileMoveJob.Status.APPROVED,
        MemoryFileMoveJob.Status.COPY_STAGED,
        MemoryFileMoveJob.Status.VERIFIED,
        MemoryFileMoveJob.Status.MANAGED_ACTIVE,
        MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
        MemoryFileMoveJob.Status.NEEDS_REVIEW,
        MemoryFileMoveJob.Status.FAILED,
    }
    expected_key = _move_idempotency_key(
        source_code=file_object.source.code,
        file_id=file_object.file_id,
        target_relative_path=target_relative_path,
        expected_sha256=file_object.current_version.sha256,
    )
    conflicts = MemoryFileMoveJob.objects.select_for_update().filter(
        file_object=file_object,
        status__in=unresolved,
    ).exclude(idempotency_key=expected_key).order_by("id")
    if conflicts.exists():
        raise ValidationError("Для файла уже существует другое нерешенное задание переноса.")


def run_move_worker(
    *,
    source: MemorySource,
    dry_run: bool = False,
    limit: int | None = None,
    require_enabled: bool = True,
) -> dict:
    if require_enabled is not True:
        raise ValueError("Обход проверки включенного источника запрещен.")
    with exclusive_file_lock(access_control_write_lock_path(), timeout=300.0):
        source = MemorySource.objects.get(pk=source.pk)
        require_enabled_file_source(source)
        return _run_move_worker_locked(source=source, dry_run=dry_run, limit=limit)


def _run_move_worker_locked(
    *,
    source: MemorySource,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict:
    try:
        profile = get_file_organization_profile(source)
    except (TypeError, ValueError) as exc:
        if dry_run:
            eligible = MemoryFileMoveJob.objects.filter(source=source, status=MemoryFileMoveJob.Status.APPROVED).count()
            return {"eligible": eligible, "moved": 0, "failed": 0, "needs_review": 0, "dry_run": True, "error": str(exc)}
        _mark_approved_jobs_needs_review(source=source, message=f"profile_invalid:{exc}")
        return {"eligible": 0, "moved": 0, "failed": 0, "needs_review": 0, "dry_run": dry_run}
    if not dry_run:
        _recover_stale_move_jobs(source=source)
    queryset = MemoryFileMoveJob.objects.filter(
        source=source,
        status=MemoryFileMoveJob.Status.APPROVED,
    ).order_by("created_at", "id")
    if limit:
        queryset = queryset[:limit]
    metrics = {"eligible": 0, "moved": 0, "failed": 0, "needs_review": 0, "dry_run": dry_run}
    for job_id in queryset.values_list("id", flat=True):
        metrics["eligible"] += 1
        if dry_run:
            continue
        claimed = _claim_move_job(job_id)
        if claimed is None:
            continue
        job, claim_token = claimed
        result = _execute_move_job_locked(job_id=job.pk, claim_token=claim_token)
        metrics[result] += 1
    return metrics


def _mark_approved_jobs_needs_review(*, source: MemorySource, message: str) -> int:
    now = timezone.now()
    return MemoryFileMoveJob.objects.filter(
        source=source,
        status=MemoryFileMoveJob.Status.APPROVED,
    ).update(
        status=MemoryFileMoveJob.Status.NEEDS_REVIEW,
        error_message=message,
        finished_at=now,
        updated_at=now,
    )


def _recover_stale_move_jobs(*, source: MemorySource, stale_after_minutes: int = 10) -> int:
    cutoff = timezone.now() - timedelta(minutes=stale_after_minutes)
    stale_phases = {
        MemoryFileMoveJob.Status.COPY_STAGED,
        MemoryFileMoveJob.Status.VERIFIED,
        MemoryFileMoveJob.Status.MANAGED_ACTIVE,
    }
    job_refs = MemoryFileMoveJob.objects.filter(
        source=source,
        status__in=stale_phases,
        started_at__lte=cutoff,
    ).values("pk", "file_object_id")
    count = 0
    for job_ref in job_refs:
        with transaction.atomic():
            locked_source = MemorySource.objects.select_for_update().get(pk=source.pk)
            file_object = MemoryFileObject.objects.select_for_update().get(pk=job_ref["file_object_id"])
            if file_object.source_id != locked_source.pk:
                continue
            locked_jobs = list(
                MemoryFileMoveJob.objects.select_for_update()
                .filter(source=locked_source, file_object=file_object)
                .order_by("id")
            )
            job = next((candidate for candidate in locked_jobs if candidate.pk == job_ref["pk"]), None)
            if job is None or job.status not in stale_phases or job.started_at is None or job.started_at > cutoff:
                continue
            manifest = dict(job.manifest or {})
            lease_until = parse_datetime(str(manifest.get("execution_lease_until", "")))
            if manifest.get("execution_started_at") and lease_until is not None and lease_until > timezone.now():
                continue
            error_code = (
                "stale_execution_started_manual_reconciliation"
                if manifest.get("execution_started_at")
                else (
                    "stale_copy_staged_claim"
                    if job.status == MemoryFileMoveJob.Status.COPY_STAGED
                    else f"stale_{job.status}_manual_reconciliation"
                )
            )
            # Preserve claim/execution/phase markers for manual recovery.
            manifest["stale_recovery_at"] = timezone.now().isoformat()
            manifest["stale_recovery_phase"] = job.status
            updated = MemoryFileMoveJob.objects.filter(
                pk=job.pk,
                status=job.status,
                updated_at=job.updated_at,
            ).update(
                status=MemoryFileMoveJob.Status.NEEDS_REVIEW,
                error_message=error_code,
                finished_at=timezone.now(),
                manifest=manifest,
                updated_at=timezone.now(),
            )
            count += int(updated == 1)
    return count


_recover_stale_copy_staged_jobs = _recover_stale_move_jobs


def execute_move_job(*, job_id: int | None = None, claim_token: str = "", job: MemoryFileMoveJob | None = None) -> str:
    with exclusive_file_lock(access_control_write_lock_path(), timeout=300.0):
        return _execute_move_job_locked(job_id=job_id, claim_token=claim_token, job=job)


def _execute_move_job_locked(*, job_id: int | None = None, claim_token: str = "", job: MemoryFileMoveJob | None = None) -> str:
    if job_id is None:
        job_id = getattr(job, "pk", None)
    if not job_id or not claim_token:
        raise ValidationError("Для выполнения задания нужен claim token.")
    with transaction.atomic():
        job_ref = MemoryFileMoveJob.objects.filter(pk=job_id).values("source_id", "file_object_id").first()
        if job_ref is None:
            raise ValidationError("Задание переноса больше не существует.")
        source = MemorySource.objects.select_for_update().get(pk=job_ref["source_id"])
        require_enabled_file_source(source)
        file_object = MemoryFileObject.objects.select_for_update().get(pk=job_ref["file_object_id"])
        locked_jobs = list(
            MemoryFileMoveJob.objects.select_for_update()
            .filter(source=source, file_object=file_object)
            .order_by("id")
        )
        job = next((candidate for candidate in locked_jobs if candidate.pk == job_id), None)
        if job is None:
            raise ValidationError("Задание переноса больше не существует.")
        manifest = dict(job.manifest or {})
        if job.status != MemoryFileMoveJob.Status.COPY_STAGED or job.started_at is None:
            raise ValidationError("Задание переноса не было атомарно захвачено worker-ом.")
        if manifest.get("claim_token") != claim_token or manifest.get("execution_started_at"):
            raise ValidationError("Задание уже выполняется или claim token недействителен.")
        manifest["execution_started_at"] = timezone.now().isoformat()
        manifest["phase"] = "COPY_STAGED"
        job.manifest = manifest
        job.save(update_fields=["manifest", "updated_at"])
    try:
        _require_source_enabled_now(source.pk)
        file_object, source, source_object, version, source_placement, source_path = _validate_job_source_state(job)
    except ValidationError as exc:
        return _mark_job_needs_review(job, str(exc), claim_token=claim_token)
    try:
        profile = get_file_organization_profile(source)
    except (TypeError, ValueError) as exc:
        return _mark_job_needs_review(job, str(exc), claim_token=claim_token)
    if profile.source_code != source.code or profile.storage_backend != MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS:
        return _mark_job_needs_review(job, "Профиль автоупорядочивания принадлежит другому источнику.", claim_token=claim_token)
    if (job.manifest or {}).get("profile_id") != profile.profile_id:
        return _mark_job_needs_review(job, "Профиль задания устарел.", claim_token=claim_token)
    if profile.physical_move_policy == "disabled":
        return _mark_job_needs_review(job, "Physical move policy is disabled.", claim_token=claim_token)
    try:
        backend = ManagedFSStorageBackend(profile.managed_root_path)
        job.manifest = {
            **(job.manifest or {}),
            "phase": "COPY_IO",
            "execution_phase_at": timezone.now().isoformat(),
            "execution_lease_until": (timezone.now() + timedelta(minutes=15)).isoformat(),
        }
        job.save(update_fields=["manifest", "updated_at"])
        _require_source_enabled_now(source.pk)
        copy_result = backend.copy_from_path(
            source_path,
            target_relative_path=job.target_relative_path,
            expected_hash=job.expected_sha256,
            expected_size=job.expected_size_bytes,
        )
        _require_source_enabled_now(source.pk)
        job.status = MemoryFileMoveJob.Status.VERIFIED
        job.target_storage_ref = copy_result.storage_ref
        job.manifest = {
            **(job.manifest or {}),
            "phase": "VERIFIED",
            "execution_phase_at": timezone.now().isoformat(),
            "execution_lease_until": (timezone.now() + timedelta(minutes=15)).isoformat(),
            "managed_storage_ref": copy_result.storage_ref,
            "managed_relative_path": copy_result.relative_path,
            "verified_sha256": copy_result.sha256,
            "verified_size_bytes": copy_result.size_bytes,
            "verified_at": timezone.now().isoformat(),
        }
        transitioned = MemoryFileMoveJob.objects.filter(
            pk=job.pk,
            status=MemoryFileMoveJob.Status.COPY_STAGED,
            manifest__claim_token=claim_token,
        ).update(
            status=MemoryFileMoveJob.Status.VERIFIED,
            target_storage_ref=copy_result.storage_ref,
            manifest=job.manifest,
            updated_at=timezone.now(),
        )
        if transitioned != 1:
            return _mark_job_needs_review(job, "Задание изменилось во время физического копирования.", claim_token=claim_token)
        job.status = MemoryFileMoveJob.Status.VERIFIED

        job.manifest = {
            **(job.manifest or {}),
            "phase": "MANAGED_ACTIVE",
            "execution_phase_at": timezone.now().isoformat(),
            "execution_lease_until": (timezone.now() + timedelta(minutes=15)).isoformat(),
        }
        job.save(update_fields=["manifest", "updated_at"])
        _require_source_enabled_now(source.pk)
        managed_placement, _created = MemoryFilePhysicalPlacement.objects.update_or_create(
            file_object=file_object,
            storage_backend=MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS,
            physical_ref=copy_result.storage_ref,
            path_role=MemoryFilePhysicalPlacement.PathRole.MANAGED_CURRENT,
            defaults={
                "source_object": source_object,
                "relative_path": copy_result.relative_path,
                "placement_status": MemoryFilePhysicalPlacement.PlacementStatus.ACTIVE,
                "is_current": True,
                "metadata": {"move_job_id": job.id, "expected_sha256": job.expected_sha256},
            },
        )
        MemoryFilePhysicalPlacement.objects.filter(file_object=file_object).exclude(id=managed_placement.id).update(is_current=False)
        source_placement.placement_status = MemoryFilePhysicalPlacement.PlacementStatus.MIGRATED
        source_placement.is_current = False
        source_placement.save(update_fields=["placement_status", "is_current", "updated_at"])
        file_object.current_physical_placement = managed_placement
        file_object.lifecycle_status = MemoryFileObject.LifecycleStatus.MANAGED_ACTIVE
        file_object.save(update_fields=["current_physical_placement", "lifecycle_status", "updated_at"])
        transitioned = MemoryFileMoveJob.objects.filter(
            pk=job.pk,
            status=MemoryFileMoveJob.Status.VERIFIED,
            manifest__claim_token=claim_token,
        ).update(status=MemoryFileMoveJob.Status.MANAGED_ACTIVE, updated_at=timezone.now())
        if transitioned != 1:
            return _mark_job_needs_review(job, "Задание изменилось перед активацией managed-файла.", claim_token=claim_token)
        job.status = MemoryFileMoveJob.Status.MANAGED_ACTIVE

        if profile.source_delete_policy.mode == "disabled":
            job.finished_at = timezone.now()
            job.save(update_fields=["finished_at", "updated_at"])
            return "moved"

        job.manifest = {
            **(job.manifest or {}),
            "phase": "QUARANTINE_IO",
            "execution_phase_at": timezone.now().isoformat(),
            "execution_lease_until": (timezone.now() + timedelta(minutes=15)).isoformat(),
        }
        job.save(update_fields=["manifest", "updated_at"])
        _require_source_enabled_now(source.pk)
        quarantine_result = backend.quarantine_source(
            source_path,
            quarantine_relative_path=_quarantine_relative_path(file_id=file_object.file_id, source_path=source_path),
            expected_hash=job.expected_sha256,
            expected_size=job.expected_size_bytes,
        )
        _require_source_enabled_now(source.pk)
        MemoryFilePhysicalPlacement.objects.update_or_create(
            file_object=file_object,
            storage_backend=MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS,
            physical_ref=quarantine_result.storage_ref,
            path_role=MemoryFilePhysicalPlacement.PathRole.QUARANTINE,
            defaults={
                "source_object": source_object,
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
            "phase": "SOURCE_QUARANTINED",
            "quarantine_storage_ref": quarantine_result.storage_ref,
            "quarantine_relative_path": quarantine_result.relative_path,
            "quarantine_sha256": quarantine_result.sha256,
            "quarantine_size_bytes": quarantine_result.size_bytes,
            "source_relative_path": source_placement.relative_path,
        }
        file_object.lifecycle_status = MemoryFileObject.LifecycleStatus.SOURCE_QUARANTINED
        file_object.save(update_fields=["lifecycle_status", "updated_at"])
        transitioned = MemoryFileMoveJob.objects.filter(
            pk=job.pk,
            status=MemoryFileMoveJob.Status.MANAGED_ACTIVE,
            manifest__claim_token=claim_token,
        ).update(
            status=MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
            retention_until=job.retention_until,
            finished_at=job.finished_at,
            manifest=job.manifest,
            updated_at=timezone.now(),
        )
        if transitioned != 1:
            return _mark_job_needs_review(job, "Задание изменилось перед переводом исходника в карантин.", claim_token=claim_token)
        job.status = MemoryFileMoveJob.Status.SOURCE_QUARANTINED
        return "moved"
    except Exception as exc:
        phase = (job.manifest or {}).get("phase", "")
        needs_review = phase in {"COPY_IO", "VERIFIED", "MANAGED_ACTIVE", "QUARANTINE_IO", "SOURCE_QUARANTINED"}
        final_status = MemoryFileMoveJob.Status.NEEDS_REVIEW if needs_review else MemoryFileMoveJob.Status.FAILED
        MemoryFileMoveJob.objects.filter(
            pk=job.pk,
            status=job.status,
            manifest__claim_token=claim_token,
        ).update(
            status=final_status,
            error_message=str(exc),
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )
        return "needs_review" if needs_review else "failed"


def _require_source_enabled_now(source_id: int) -> None:
    """Fence each physical phase against a concurrent source shutdown."""
    if not MemorySource.objects.filter(
        pk=source_id,
        status=MemorySource.Status.ENABLED,
    ).exists():
        raise ValidationError("Источник отключен во время физической операции.")


def purge_ready_source_files(
    *,
    source: MemorySource,
    backup_checkpoint_ref: str = "",
    dry_run: bool = False,
    require_enabled: bool = True,
) -> dict:
    if require_enabled is not True:
        raise ValueError("Обход проверки включенного источника запрещен.")
    with exclusive_file_lock(access_control_write_lock_path(), timeout=300.0):
        return _purge_ready_source_files_locked(
            source=source,
            backup_checkpoint_ref=backup_checkpoint_ref,
            dry_run=dry_run,
        )


def _purge_ready_source_files_locked(
    *,
    source: MemorySource,
    backup_checkpoint_ref: str = "",
    dry_run: bool = False,
) -> dict:
    source = MemorySource.objects.get(pk=source.pk)
    require_enabled_file_source(source)
    try:
        profile = get_file_organization_profile(source)
    except (TypeError, ValueError) as exc:
        eligible = MemoryFileMoveJob.objects.filter(
            source=source,
            status=MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
            retention_until__lte=timezone.now(),
        ).count()
        if not dry_run:
            MemoryFileMoveJob.objects.filter(
                source=source,
                status=MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
                retention_until__lte=timezone.now(),
            ).update(
                status=MemoryFileMoveJob.Status.NEEDS_REVIEW,
                error_message=f"profile_invalid:{exc}",
                finished_at=timezone.now(),
                updated_at=timezone.now(),
            )
        return {"eligible": eligible, "purged": 0, "blocked": eligible, "needs_review": eligible, "dry_run": dry_run, "error": str(exc)}
    now = timezone.now()
    job_refs = list(MemoryFileMoveJob.objects.filter(
        source=source,
        status=MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
        retention_until__lte=now,
    ).values("pk", "file_object_id"))
    metrics = {"eligible": len(job_refs), "purged": 0, "blocked": 0, "dry_run": dry_run}
    if profile.source_delete_policy.mode != "quarantine_then_purge":
        metrics["blocked"] = metrics["eligible"]
        return metrics
    if profile.source_delete_policy.requires_backup_checkpoint and not backup_checkpoint_ref:
        metrics["blocked"] = metrics["eligible"]
        return metrics
    backend = ManagedFSStorageBackend(profile.managed_root_path)
    managed_root = profile.managed_root_path.resolve()
    for job_ref in job_refs:
        if dry_run:
            job = MemoryFileMoveJob.objects.filter(
                pk=job_ref["pk"],
                source=source,
                status=MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
            ).first()
            purge_token = ""
        else:
            claimed = _claim_purge_job(job_id=job_ref["pk"], source_id=source.pk)
            if claimed is None:
                metrics["blocked"] += 1
                continue
            job, purge_token = claimed
        if job is None or job.status != MemoryFileMoveJob.Status.SOURCE_QUARANTINED:
            metrics["blocked"] += 1
            continue
        quarantine_ref = (job.manifest or {}).get("quarantine_storage_ref", "")
        if not quarantine_ref:
            if not dry_run:
                _mark_purge_needs_review(job, purge_token, "quarantine_reference_missing", dry_run=False)
            metrics["blocked"] += 1
            continue
        quarantine_path = _validated_quarantine_path(quarantine_ref, managed_root=managed_root)
        if quarantine_path is None:
            if not dry_run:
                _mark_purge_needs_review(job, purge_token, "quarantine_path_outside_managed_root", dry_run=False)
            metrics["blocked"] += 1
            continue
        # PURGE_IO is a committed intent record.  If the file is already gone,
        # the previous process completed unlink and crashed before DB finalize.
        if not dry_run and (job.manifest or {}).get("phase") == "PURGE_IO" and not quarantine_path.exists():
            if _finalize_purged_job(
                job_id=job.pk,
                purge_token=purge_token,
                quarantine_ref=quarantine_ref,
                backup_checkpoint_ref=backup_checkpoint_ref,
            ):
                metrics["purged"] += 1
            else:
                metrics["blocked"] += 1
            continue
        if not backend.verify(
            quarantine_ref,
            expected_hash=(job.manifest or {}).get("quarantine_sha256", job.expected_sha256),
            expected_size=(job.manifest or {}).get("quarantine_size_bytes", job.expected_size_bytes),
        ):
            if not dry_run:
                _mark_purge_needs_review(job, purge_token, "quarantine_content_changed", dry_run=False)
            metrics["blocked"] += 1
            continue
        if dry_run:
            metrics["purged"] += 1
            continue
        if not _mark_purge_io(job=job, purge_token=purge_token):
            metrics["blocked"] += 1
            continue
        job.refresh_from_db()
        quarantine_ref = (job.manifest or {}).get("quarantine_storage_ref", "")
        quarantine_path = _validated_quarantine_path(quarantine_ref, managed_root=managed_root)
        if quarantine_path is None:
            _mark_purge_needs_review(job, purge_token, "quarantine_path_outside_managed_root", dry_run=False)
            metrics["blocked"] += 1
            continue
        if not backend.verify(
            quarantine_ref,
            expected_hash=(job.manifest or {}).get("quarantine_sha256", job.expected_sha256),
            expected_size=(job.manifest or {}).get("quarantine_size_bytes", job.expected_size_bytes),
        ):
            _mark_purge_needs_review(job, purge_token, "quarantine_content_changed", dry_run=False)
            metrics["blocked"] += 1
            continue
        purge_ok = backend.purge(quarantine_ref)
        if not purge_ok or quarantine_path.exists():
            failed_manifest = {
                **(job.manifest or {}),
                "phase": "PURGE_NEEDS_REVIEW",
                "purge_failed_at": timezone.now().isoformat(),
            }
            MemoryFileMoveJob.objects.filter(
                pk=job.pk,
                status=MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
                manifest__purge_token=(job.manifest or {}).get("purge_token", ""),
            ).update(
                status=MemoryFileMoveJob.Status.NEEDS_REVIEW,
                error_message="purge_postcondition_failed",
                manifest=failed_manifest,
                finished_at=timezone.now(),
                updated_at=timezone.now(),
            )
            metrics["blocked"] += 1
            continue
        if not _finalize_purged_job(
            job_id=job.pk,
            purge_token=purge_token,
            quarantine_ref=quarantine_ref,
            backup_checkpoint_ref=backup_checkpoint_ref,
        ):
            metrics["blocked"] += 1
            continue
        metrics["purged"] += 1
    return metrics


@transaction.atomic
def _claim_purge_job(*, job_id: int, source_id: int):
    source = MemorySource.objects.select_for_update().get(pk=source_id)
    require_enabled_file_source(source)
    ref = MemoryFileMoveJob.objects.filter(pk=job_id, source=source).values("file_object_id").first()
    if ref is None:
        return None
    file_object = MemoryFileObject.objects.select_for_update().get(pk=ref["file_object_id"])
    jobs = list(
        MemoryFileMoveJob.objects.select_for_update()
        .filter(source=source, file_object=file_object)
        .order_by("id")
    )
    job = next((candidate for candidate in jobs if candidate.pk == job_id), None)
    if job is None or job.status != MemoryFileMoveJob.Status.SOURCE_QUARANTINED:
        return None
    manifest = dict(job.manifest or {})
    if manifest.get("phase") == "PURGE_IO" and manifest.get("purge_token"):
        return job, manifest["purge_token"]
    token = secrets.token_urlsafe(24)
    job.manifest = {
        **manifest,
        "phase": "PURGE_STARTED",
        "purge_token": token,
        "purge_started_at": timezone.now().isoformat(),
    }
    job.save(update_fields=["manifest", "updated_at"])
    return job, token


def _validated_quarantine_path(quarantine_ref: str, *, managed_root: Path) -> Path | None:
    path = Path(quarantine_ref)
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return None
    if path.is_symlink() or (resolved != managed_root and managed_root not in resolved.parents):
        return None
    return path


def _mark_purge_io(*, job: MemoryFileMoveJob, purge_token: str) -> bool:
    manifest = {
        **(job.manifest or {}),
        "phase": "PURGE_IO",
        "purge_io_started_at": timezone.now().isoformat(),
    }
    updated = MemoryFileMoveJob.objects.filter(
        pk=job.pk,
        status=MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
        manifest__purge_token=purge_token,
    ).update(manifest=manifest, updated_at=timezone.now())
    if updated == 1:
        job.manifest = manifest
    return updated == 1


@transaction.atomic
def _finalize_purged_job(
    *,
    job_id: int,
    purge_token: str,
    quarantine_ref: str,
    backup_checkpoint_ref: str,
) -> bool:
    ref = MemoryFileMoveJob.objects.filter(pk=job_id).values("source_id", "file_object_id").first()
    if ref is None:
        return False
    source = MemorySource.objects.select_for_update().get(pk=ref["source_id"])
    require_enabled_file_source(source)
    file_object = MemoryFileObject.objects.select_for_update().get(pk=ref["file_object_id"])
    jobs = list(
        MemoryFileMoveJob.objects.select_for_update()
        .filter(source=source, file_object=file_object)
        .order_by("id")
    )
    job = next((candidate for candidate in jobs if candidate.pk == job_id), None)
    if (
        job is None
        or job.status != MemoryFileMoveJob.Status.SOURCE_QUARANTINED
        or (job.manifest or {}).get("phase") != "PURGE_IO"
        or (job.manifest or {}).get("purge_token") != purge_token
        or (job.manifest or {}).get("quarantine_storage_ref") != quarantine_ref
        or Path(quarantine_ref).exists()
    ):
        return False
    MemoryFilePhysicalPlacement.objects.select_for_update().filter(
        file_object=file_object,
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
    job.manifest = {
        **(job.manifest or {}),
        "phase": "SOURCE_PURGED",
        "purge_finished_at": timezone.now().isoformat(),
    }
    job.save(update_fields=["status", "backup_checkpoint_ref", "manifest", "updated_at"])
    file_object.lifecycle_status = MemoryFileObject.LifecycleStatus.SOURCE_PURGED
    file_object.save(update_fields=["lifecycle_status", "updated_at"])
    return True


def _mark_job_needs_review(job: MemoryFileMoveJob, message: str, *, claim_token: str = "") -> str:
    now = timezone.now()
    filters = {"pk": job.pk, "status": job.status}
    if claim_token:
        filters["manifest__claim_token"] = claim_token
    updated = MemoryFileMoveJob.objects.filter(**filters).update(
        status=MemoryFileMoveJob.Status.NEEDS_REVIEW,
        error_message=message,
        finished_at=now,
        updated_at=now,
    )
    if updated != 1:
        return "needs_review"
    return "needs_review"


def _mark_purge_needs_review(job: MemoryFileMoveJob, purge_token: str, message: str, *, dry_run: bool) -> None:
    if dry_run:
        return
    manifest = {
        **(job.manifest or {}),
        "phase": "PURGE_NEEDS_REVIEW",
        "purge_failed_at": timezone.now().isoformat(),
    }
    MemoryFileMoveJob.objects.filter(
        pk=job.pk,
        status=MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
        manifest__purge_token=purge_token,
    ).update(
        status=MemoryFileMoveJob.Status.NEEDS_REVIEW,
        error_message=message,
        manifest=manifest,
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


@transaction.atomic
def _claim_move_job(job_id: int) -> tuple[MemoryFileMoveJob, str] | None:
    """Claim one APPROVED job with a conditional update before file I/O."""

    now = timezone.now()
    # Read the target identity without a lock first.  Every lock in this
    # operation then follows file -> all jobs (stable id order) -> target.
    target_ref = MemoryFileMoveJob.objects.filter(pk=job_id).values("file_object_id", "source_id").first()
    if target_ref is None:
        return None
    source = MemorySource.objects.select_for_update().get(pk=target_ref["source_id"])
    file_object = MemoryFileObject.objects.select_for_update().get(pk=target_ref["file_object_id"])
    unresolved = {
        MemoryFileMoveJob.Status.PLANNED,
        MemoryFileMoveJob.Status.APPROVED,
        MemoryFileMoveJob.Status.COPY_STAGED,
        MemoryFileMoveJob.Status.VERIFIED,
        MemoryFileMoveJob.Status.MANAGED_ACTIVE,
        MemoryFileMoveJob.Status.SOURCE_QUARANTINED,
        MemoryFileMoveJob.Status.NEEDS_REVIEW,
        MemoryFileMoveJob.Status.FAILED,
    }
    # Lock every job for this stable file identity in one deterministic order.
    # Filtering only unresolved rows would leave a concurrent terminal-row
    # insert/update outside the lock protocol and make the lock order less
    # explicit for reviewers and database backends.
    jobs = list(
        MemoryFileMoveJob.objects.select_for_update()
        .filter(file_object=file_object, source=source)
        .order_by("id")
    )
    job = MemoryFileMoveJob.objects.select_for_update().get(pk=job_id)
    if job.status != MemoryFileMoveJob.Status.APPROVED:
        return None
    conflicts = [candidate for candidate in jobs if candidate.pk != job.pk and candidate.status in unresolved]
    if conflicts:
        job.status = MemoryFileMoveJob.Status.NEEDS_REVIEW
        job.error_message = "duplicate_active_move_job"
        job.finished_at = now
        job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        return None
    job.status = MemoryFileMoveJob.Status.COPY_STAGED
    job.attempts += 1
    job.started_at = now
    token = secrets.token_urlsafe(32)
    job.manifest = {
        **(job.manifest or {}),
        "claim_token": token,
        "claimed_at": now.isoformat(),
        "execution_lease_until": (now + timedelta(minutes=15)).isoformat(),
        "phase": "COPY_STAGED",
    }
    job.save(update_fields=["status", "attempts", "started_at", "manifest", "updated_at"])
    return job, token


@transaction.atomic
def _validate_job_source_state(job: MemoryFileMoveJob):
    """Reloaded relationship and path checks immediately before file I/O."""

    job_ref = MemoryFileMoveJob.objects.filter(pk=job.pk).values(
        "source_id", "file_object_id", "source_placement_id"
    ).first()
    if job_ref is None:
        raise ValidationError("Задание переноса больше не существует.")
    source = MemorySource.objects.select_for_update().get(pk=job_ref["source_id"])
    file_object = MemoryFileObject.objects.select_for_update().get(pk=job_ref["file_object_id"])
    locked_jobs = list(
        MemoryFileMoveJob.objects.select_for_update()
        .filter(source=source, file_object=file_object)
        .order_by("id")
    )
    job = next((candidate for candidate in locked_jobs if candidate.pk == job.pk), None)
    if job is None:
        raise ValidationError("Задание переноса больше не существует.")
    source_object = None
    source_placement = (
        MemoryFilePhysicalPlacement.objects.select_for_update()
        .filter(pk=job_ref["source_placement_id"], file_object=file_object)
        .first()
    )
    if source_placement is not None and source_placement.source_object_id:
        source_object = MemorySourceObject.objects.select_for_update().get(pk=source_placement.source_object_id)
    if file_object.source_id != job.source_id or source_placement is None or source_object is None:
        raise ValidationError("Связи задания с источником или файлом устарели.")
    version = MemoryFileObjectVersion.objects.select_for_update().filter(pk=file_object.current_version_id).first()
    if (
        version is None
        or version.version_status != MemoryFileObjectVersion.VersionStatus.CURRENT
        or version.source_object_id != source_placement.source_object_id
        or source_placement.storage_backend != MemoryFilePhysicalPlacement.StorageBackend.SOURCE_FS
        or source_placement.path_role != MemoryFilePhysicalPlacement.PathRole.SOURCE_CURRENT
        or source_placement.placement_status != MemoryFilePhysicalPlacement.PlacementStatus.ACTIVE
        or not source_placement.is_current
        or file_object.current_physical_placement_id != source_placement.pk
        or source_object.source_id != job.source_id
        or source_placement.physical_ref != source_object.object_uri
        or source_placement.relative_path != source_object.relative_path
        or file_object.lifecycle_status not in {
            MemoryFileObject.LifecycleStatus.SOURCE_ACTIVE,
            MemoryFileObject.LifecycleStatus.MOVE_PLANNED,
        }
    ):
        raise ValidationError("Текущая версия файла не соответствует исходному размещению.")
    if version.sha256 != job.expected_sha256 or version.size_bytes != job.expected_size_bytes:
        raise ValidationError("Текущая версия файла изменилась после согласования.")
    from apps.memory.document_ingestion import resolve_source_root

    root = resolve_source_root(source).resolve()
    source_path = Path(source_placement.physical_ref)
    if source_path.is_symlink():
        raise ValidationError("Исходный путь является символической ссылкой.")
    try:
        resolved = source_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValidationError("Исходный файл отсутствует.") from exc
    if resolved != root and root not in resolved.parents:
        raise ValidationError("Исходный путь выходит за пределы корня источника.")
    expected_path = (root / normalize_relative_path(source_object.relative_path)).resolve()
    if expected_path != resolved:
        raise ValidationError("Исходный физический путь не совпадает с относительным путем объекта.")
    if not resolved.is_file():
        raise ValidationError("Исходный путь не является обычным файлом.")
    if resolved.stat().st_size != job.expected_size_bytes or sha256_file(resolved) != job.expected_sha256:
        raise ValidationError("Исходный файл изменился после согласования.")
    return file_object, source, source_object, version, source_placement, resolved


def _membership_fingerprint(*, source, bucket: str, file_ids: list[str]) -> str:
    payload = {"source": source.code, "bucket": bucket, "file_ids": sorted(file_ids)}
    return "sha256:" + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _lock_active_actor(actor):
    from django.contrib.auth import get_user_model

    if not is_active_actor(actor):
        raise PermissionDenied("Действие доступно только активному пользователю.")
    current = get_user_model().objects.select_for_update().filter(pk=actor.pk, is_active=True).first()
    if current is None or not is_active_actor(current):
        raise PermissionDenied("Действие доступно только активному пользователю.")
    return current


def _current_source_placement(file_object: MemoryFileObject) -> MemoryFilePhysicalPlacement | None:
    return (
        MemoryFilePhysicalPlacement.objects.filter(
            file_object=file_object,
            source_object__source_id=file_object.source_id,
            storage_backend=MemoryFilePhysicalPlacement.StorageBackend.SOURCE_FS,
            path_role=MemoryFilePhysicalPlacement.PathRole.SOURCE_CURRENT,
            placement_status=MemoryFilePhysicalPlacement.PlacementStatus.ACTIVE,
            is_current=True,
            pk=getattr(file_object, "current_physical_placement_id", None),
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


def _quarantine_relative_path(*, file_id: str, source_path: Path) -> str:
    file_name = sanitize_path_segment(source_path.name, fallback="file")
    return normalize_relative_path(f"quarantine/{file_id}/{file_name}")
