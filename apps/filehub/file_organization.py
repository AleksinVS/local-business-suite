from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.memory.models import MemoryIngestionIssue, MemorySource, MemorySourceObject

from .models import (
    MemoryFileObject,
    MemoryFileObjectVersion,
    MemoryFilePathAlias,
    MemoryFilePhysicalPlacement,
    MemoryFileVirtualView,
)


BASELINE_VIEW_SLUG = "baseline_auto_v1"
ORGANIZATION_VIEW_SLUG = "organization_accepted"


@dataclass(frozen=True)
class SourceDeletePolicy:
    mode: str
    retention_days: int
    requires_backup_checkpoint: bool


@dataclass(frozen=True)
class ProposalThresholds:
    min_users: int
    min_events: int
    min_files: int
    min_confidence: float


@dataclass(frozen=True)
class FileOrganizationProfile:
    profile_id: str
    enabled: bool
    source_code: str
    incoming_path: str
    managed_root: str
    baseline_profile: str
    physical_move_policy: str
    source_delete_policy: SourceDeletePolicy
    storage_backend: str
    future_backends: tuple[str, ...]
    proposal_thresholds: ProposalThresholds

    @property
    def incoming_relative_path(self) -> str:
        return normalize_relative_path(self.incoming_path)

    @property
    def managed_root_path(self) -> Path:
        root = Path(self.managed_root)
        if root.is_absolute():
            return root
        return settings.BASE_DIR / root


def get_file_organization_profile(source: MemorySource, *, require_enabled: bool = True) -> FileOrganizationProfile:
    payload = getattr(settings, "LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES", {}) or {}
    profile_id = (source.config or {}).get("file_organization_profile") or ""
    raw_profile = None
    if profile_id:
        raw_profile = (payload.get("profiles") or {}).get(profile_id)
    if raw_profile is None:
        for candidate_id, candidate in (payload.get("profiles") or {}).items():
            if candidate.get("source_code") == source.code:
                profile_id = candidate_id
                raw_profile = candidate
                break
    if raw_profile is None:
        raise ValueError(f"File organization profile for source '{source.code}' is not configured.")
    profile = FileOrganizationProfile(
        profile_id=profile_id,
        enabled=bool(raw_profile.get("enabled", False)),
        source_code=str(raw_profile["source_code"]),
        incoming_path=str(raw_profile["incoming_path"]),
        managed_root=str(raw_profile["managed_root"]),
        baseline_profile=str(raw_profile["baseline_profile"]),
        physical_move_policy=str(raw_profile["physical_move_policy"]),
        source_delete_policy=SourceDeletePolicy(
            mode=str(raw_profile["source_delete_policy"]["mode"]),
            retention_days=int(raw_profile["source_delete_policy"]["retention_days"]),
            requires_backup_checkpoint=bool(raw_profile["source_delete_policy"]["requires_backup_checkpoint"]),
        ),
        storage_backend=str(raw_profile["storage_backend"]),
        future_backends=tuple(raw_profile.get("future_backends") or ()),
        proposal_thresholds=ProposalThresholds(
            min_users=int(raw_profile["proposal_thresholds"]["min_users"]),
            min_events=int(raw_profile["proposal_thresholds"]["min_events"]),
            min_files=int(raw_profile["proposal_thresholds"]["min_files"]),
            min_confidence=float(raw_profile["proposal_thresholds"]["min_confidence"]),
        ),
    )
    if require_enabled and not profile.enabled:
        raise ValueError(f"File organization profile '{profile.profile_id}' is disabled.")
    return profile


def stable_file_id_for_source_object(source_object: MemorySourceObject) -> str:
    hash_value = source_object.content_hash or ""
    size_value = source_object.size_bytes or 0
    if hash_value:
        basis = f"{source_object.source.code}:sha256:{hash_value}:size:{size_value}"
    else:
        basis = f"{source_object.source.code}:object:{source_object.object_id}:size:{size_value}"
    return "file:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:40]


@transaction.atomic
def ensure_file_object_for_source_object(source_object: MemorySourceObject) -> MemoryFileObject:
    now = timezone.now()
    file_id = stable_file_id_for_source_object(source_object)
    file_object, _created = MemoryFileObject.objects.update_or_create(
        file_id=file_id,
        defaults={
            "source": source_object.source,
            "last_seen_at": source_object.last_seen_at or now,
            "metadata": {
                "identity_basis": "sha256_size" if source_object.content_hash else "source_object_fallback",
                "source_code": source_object.source.code,
            },
        },
    )
    version, _version_created = MemoryFileObjectVersion.objects.update_or_create(
        file_object=file_object,
        sha256=source_object.content_hash or "",
        size_bytes=source_object.size_bytes or 0,
        defaults={
            "source_object": source_object,
            "mtime": source_object.mtime,
            "storage_backend": MemoryFilePhysicalPlacement.StorageBackend.SOURCE_FS,
            "storage_ref": source_object.object_uri,
            "version_status": MemoryFileObjectVersion.VersionStatus.CURRENT,
            "metadata": {
                "source_object_id": source_object.object_id,
                "relative_path": source_object.relative_path,
            },
        },
    )
    placement, _placement_created = MemoryFilePhysicalPlacement.objects.update_or_create(
        file_object=file_object,
        storage_backend=MemoryFilePhysicalPlacement.StorageBackend.SOURCE_FS,
        physical_ref=source_object.object_uri,
        path_role=MemoryFilePhysicalPlacement.PathRole.SOURCE_CURRENT,
        defaults={
            "source_object": source_object,
            "relative_path": source_object.relative_path,
            "placement_status": MemoryFilePhysicalPlacement.PlacementStatus.ACTIVE,
            "is_current": True,
            "metadata": {
                "content_hash": source_object.content_hash,
                "size_bytes": source_object.size_bytes,
            },
        },
    )
    MemoryFilePathAlias.objects.update_or_create(
        file_object=file_object,
        source=source_object.source,
        relative_path=source_object.relative_path,
        alias_kind=MemoryFilePathAlias.AliasKind.CURRENT,
        defaults={
            "is_active": True,
            "last_seen_at": source_object.last_seen_at or now,
            "metadata": {"source_object_id": source_object.object_id},
        },
    )
    updates = []
    if file_object.current_version_id != version.id:
        file_object.current_version = version
        updates.append("current_version")
    if file_object.current_physical_placement_id != placement.id:
        file_object.current_physical_placement = placement
        updates.append("current_physical_placement")
    if file_object.lifecycle_status in {MemoryFileObject.LifecycleStatus.BLOCKED, MemoryFileObject.LifecycleStatus.NEEDS_REVIEW}:
        file_object.lifecycle_status = MemoryFileObject.LifecycleStatus.SOURCE_ACTIVE
        updates.append("lifecycle_status")
    if updates:
        updates.append("updated_at")
        file_object.save(update_fields=updates)
    return file_object


def sync_file_objects_from_source_objects(*, source: MemorySource, dry_run: bool = False, limit: int | None = None) -> dict:
    queryset = MemorySourceObject.objects.filter(source=source).order_by("relative_path")
    if limit:
        queryset = queryset[:limit]
    metrics = {"seen": 0, "linked": 0, "duplicates": 0, "dry_run": dry_run}
    seen_file_ids = set()
    for source_object in queryset:
        metrics["seen"] += 1
        file_id = stable_file_id_for_source_object(source_object)
        if file_id in seen_file_ids:
            metrics["duplicates"] += 1
        seen_file_ids.add(file_id)
        if not dry_run:
            ensure_file_object_for_source_object(source_object)
            metrics["linked"] += 1
    return metrics


def get_or_create_system_view(
    *,
    source: MemorySource,
    view_kind: str,
    slug: str,
    title: str,
    baseline_profile: str = "",
    dry_run: bool = False,
) -> MemoryFileVirtualView | None:
    if dry_run:
        return None
    view, _created = MemoryFileVirtualView.objects.update_or_create(
        source=source,
        view_kind=view_kind,
        slug=slug,
        defaults={
            "title": title,
            "status": MemoryFileVirtualView.Status.ACTIVE,
            "is_system": True,
            "baseline_profile": baseline_profile,
            "generated_at": timezone.now(),
        },
    )
    return view


def create_file_organization_issue(
    *,
    source: MemorySource,
    source_object: MemorySourceObject | None,
    message: str,
    metadata: dict,
    severity=MemoryIngestionIssue.Severity.WARNING,
    issue_kind=MemoryIngestionIssue.IssueKind.CANONICALIZATION_CONFLICT,
) -> MemoryIngestionIssue:
    return MemoryIngestionIssue.objects.create(
        source=source,
        source_object=source_object,
        issue_kind=issue_kind,
        severity=severity,
        message=message,
        metadata=safe_issue_metadata(metadata),
    )


def safe_issue_metadata(metadata: dict) -> dict:
    safe = {}
    for key, value in (metadata or {}).items():
        if key in {"raw_content", "text", "full_unc_path", "physical_ref"}:
            continue
        safe[key] = value
    return safe


def normalize_relative_path(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part not in {"", ".", ".."}]
    return "/".join(parts)


def sanitize_path_segment(value: str, *, fallback: str = "Без названия") -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:120] or fallback


def decimal_confidence(value: float | Decimal) -> Decimal:
    return Decimal(str(max(0.0, min(1.0, float(value))))).quantize(Decimal("0.0001"))


def path_bucket(virtual_path: str) -> str:
    path = normalize_relative_path(virtual_path)
    if not path:
        return ""
    return sanitize_path_segment(path.split("/")[0], fallback="Прочее")


def safe_path_hash(virtual_path: str) -> str:
    return hashlib.sha256(normalize_relative_path(virtual_path).encode("utf-8")).hexdigest()
