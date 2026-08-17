from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.memory.models import MemoryIngestionIssue, MemorySource, MemorySourceObject

from .models import (
    MemoryFileObject,
    MemoryFileObjectVersion,
    MemoryFilePathAlias,
    MemoryFilePhysicalPlacement,
    MemoryFileUsageEvent,
    MemoryFileVirtualPlacement,
    MemoryFileVirtualView,
)
from apps.memory.policies import is_active_actor
from apps.core.file_locks import access_control_write_lock_path, exclusive_file_lock
from .selectors import can_access_file_object


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
    # The old flag was exposed by management commands as an escape hatch for
    # disabled sources.  File organization is a write-capable contour, so a
    # caller must never be able to weaken this invariant.  Keep the keyword
    # temporarily for compatibility with older command wrappers, but reject
    # an attempted bypass explicitly.
    if require_enabled is not True:
        raise ValueError("Обход проверки включенного источника запрещен.")
    require_enabled_file_source(source)
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
    if profile.source_code != source.code:
        raise ValueError(
            f"File organization profile '{profile.profile_id}' belongs to source '{profile.source_code}', "
            f"not '{source.code}'."
        )
    if not profile.enabled:
        raise ValueError(f"File organization profile '{profile.profile_id}' is disabled.")
    return profile


def require_enabled_file_source(source: MemorySource) -> None:
    """Fail closed before any file-organization read or write operation."""
    if getattr(source, "status", None) != MemorySource.Status.ENABLED:
        raise ValueError(
            f"Источник '{source.code}' не включен для операций "
            "автоупорядочивания."
        )


def stable_file_id_for_source_object(source_object: MemorySourceObject) -> str:
    hash_value = source_object.content_hash or ""
    size_value = source_object.size_bytes or 0
    if hash_value:
        basis = f"{source_object.source.code}:sha256:{hash_value}:size:{size_value}"
    else:
        basis = f"{source_object.source.code}:object:{source_object.object_id}:size:{size_value}"
    return "file:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:40]


def ensure_file_object_for_source_object(source_object: MemorySourceObject) -> MemoryFileObject:
    """Locking public adapter for the source-object linker.

    The actual primitive is private and is only called by callers that already
    hold the common file-organization lock.  Keeping this wrapper preserves
    the small service API without leaving an unlocked write path.
    """
    with exclusive_file_lock(access_control_write_lock_path(), timeout=300.0):
        with transaction.atomic():
            return _ensure_file_object_for_source_object_locked(source_object=source_object)


@transaction.atomic
def _ensure_file_object_for_source_object_locked(*, source_object: MemorySourceObject) -> MemoryFileObject:
    source = MemorySource.objects.select_for_update().get(pk=source_object.source_id)
    require_enabled_file_source(source)
    source_object = MemorySourceObject.objects.select_related("source").get(pk=source_object.pk)
    now = timezone.now()
    file_id = stable_file_id_for_source_object(source_object)
    file_object = MemoryFileObject.objects.select_for_update().filter(file_id=file_id).first()
    if file_object is None:
        file_object = MemoryFileObject.objects.create(
            file_id=file_id,
            source=source,
            last_seen_at=source_object.last_seen_at or now,
            metadata={
                "identity_basis": "sha256_size" if source_object.content_hash else "source_object_fallback",
                "source_code": source.code,
            },
        )
        was_source_current = True
    else:
        managed_current = (
            MemoryFilePhysicalPlacement.objects.select_for_update()
            .filter(
                file_object=file_object,
                storage_backend=MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS,
                path_role=MemoryFilePhysicalPlacement.PathRole.MANAGED_CURRENT,
                placement_status=MemoryFilePhysicalPlacement.PlacementStatus.ACTIVE,
                is_current=True,
            )
            .order_by("id")
            .first()
        )
        managed_side_effect = managed_current is not None or (
            file_object.current_physical_placement_id is not None
            and file_object.current_physical_placement.storage_backend
            == MemoryFilePhysicalPlacement.StorageBackend.MANAGED_FS
        )
        if managed_current is not None and file_object.current_physical_placement_id != managed_current.pk:
            MemoryFilePhysicalPlacement.objects.select_for_update().filter(
                file_object=file_object,
                storage_backend=MemoryFilePhysicalPlacement.StorageBackend.SOURCE_FS,
                is_current=True,
            ).update(
                placement_status=MemoryFilePhysicalPlacement.PlacementStatus.MIGRATED,
                is_current=False,
                updated_at=now,
            )
            file_object.current_physical_placement = managed_current
            file_object.lifecycle_status = MemoryFileObject.LifecycleStatus.MANAGED_ACTIVE
            file_object.save(
                update_fields=[
                    "current_physical_placement",
                    "lifecycle_status",
                    "last_seen_at",
                    "metadata",
                    "updated_at",
                ]
            )
        was_source_current = not managed_side_effect and file_object.lifecycle_status in {
            MemoryFileObject.LifecycleStatus.SOURCE_ACTIVE,
            MemoryFileObject.LifecycleStatus.MOVE_PLANNED,
        }
        file_object.last_seen_at = source_object.last_seen_at or now
        file_object.metadata = {
            "identity_basis": "sha256_size" if source_object.content_hash else "source_object_fallback",
            "source_code": source.code,
        }
        file_object.save(update_fields=["last_seen_at", "metadata", "updated_at"])
    version, _version_created = MemoryFileObjectVersion.objects.update_or_create(
        file_object=file_object,
        sha256=source_object.content_hash or "",
        size_bytes=source_object.size_bytes or 0,
        defaults={
            "source_object": source_object,
            "mtime": source_object.mtime,
            "storage_backend": MemoryFilePhysicalPlacement.StorageBackend.SOURCE_FS,
            "storage_ref": source_object.object_uri,
            "version_status": (
                MemoryFileObjectVersion.VersionStatus.CURRENT
                if was_source_current
                else MemoryFileObjectVersion.VersionStatus.HISTORICAL
            ),
            "metadata": {
                "source_object_id": source_object.object_id,
                "relative_path": source_object.relative_path,
            },
        },
    )
    # Do not demote the version currently referenced by a managed file merely
    # because the source was rediscovered.  New source versions remain
    # historical, while an already-current version keeps its status.
    if not was_source_current and file_object.current_version_id == version.id:
        if version.version_status != MemoryFileObjectVersion.VersionStatus.CURRENT:
            version.version_status = MemoryFileObjectVersion.VersionStatus.CURRENT
            version.save(update_fields=["version_status", "updated_at"])
    if was_source_current:
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
    else:
        # Once a physical move, quarantine, purge, block, or review state has
        # been reached, source discovery is history only.  Never recreate a
        # SOURCE_CURRENT placement or point the file back at the source.
        placement, _placement_created = MemoryFilePhysicalPlacement.objects.update_or_create(
            file_object=file_object,
            storage_backend=MemoryFilePhysicalPlacement.StorageBackend.SOURCE_FS,
            physical_ref=source_object.object_uri,
            path_role=MemoryFilePhysicalPlacement.PathRole.SOURCE_ALIAS,
            defaults={
                "source_object": source_object,
                "relative_path": source_object.relative_path,
                "placement_status": MemoryFilePhysicalPlacement.PlacementStatus.MIGRATED,
                "is_current": False,
                "metadata": {
                    "content_hash": source_object.content_hash,
                    "size_bytes": source_object.size_bytes,
                    "historical_after_lifecycle": file_object.lifecycle_status,
                },
            },
        )
    MemoryFilePathAlias.objects.update_or_create(
        file_object=file_object,
        source=source,
        relative_path=source_object.relative_path,
        alias_kind=(
            MemoryFilePathAlias.AliasKind.CURRENT
            if was_source_current
            else MemoryFilePathAlias.AliasKind.PREVIOUS
        ),
        defaults={
            "is_active": was_source_current,
            "last_seen_at": source_object.last_seen_at or now,
            "metadata": {"source_object_id": source_object.object_id},
        },
    )
    updates = []
    if was_source_current and file_object.current_version_id != version.id:
        file_object.current_version = version
        updates.append("current_version")
    if was_source_current and file_object.current_physical_placement_id != placement.id:
        file_object.current_physical_placement = placement
        updates.append("current_physical_placement")
    if was_source_current and file_object.lifecycle_status in {MemoryFileObject.LifecycleStatus.BLOCKED, MemoryFileObject.LifecycleStatus.NEEDS_REVIEW}:
        file_object.lifecycle_status = MemoryFileObject.LifecycleStatus.SOURCE_ACTIVE
        updates.append("lifecycle_status")
    if updates:
        updates.append("updated_at")
        file_object.save(update_fields=updates)
    return file_object


def sync_file_objects_from_source_objects(*, source: MemorySource, dry_run: bool = False, limit: int | None = None) -> dict:
    with exclusive_file_lock(access_control_write_lock_path(), timeout=300.0):
        with transaction.atomic():
            source = MemorySource.objects.select_for_update().get(pk=source.pk)
            get_file_organization_profile(source)
            return _sync_file_objects_from_source_objects_locked(source=source, dry_run=dry_run, limit=limit)


def _sync_file_objects_from_source_objects_locked(*, source: MemorySource, dry_run: bool = False, limit: int | None = None) -> dict:
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
            _ensure_file_object_for_source_object_locked(source_object=source_object)
            metrics["linked"] += 1
    return metrics


def save_user_virtual_placement(*, actor, file_object_id: int, virtual_path: str) -> MemoryFileVirtualPlacement:
    with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
        with transaction.atomic():
            return _save_user_virtual_placement_locked(
                actor=actor,
                file_object_id=file_object_id,
                virtual_path=virtual_path,
            )


def _save_user_virtual_placement_locked(*, actor, file_object_id: int, virtual_path: str) -> MemoryFileVirtualPlacement:
    """Actor-aware personal placement command used by HTTP and services."""

    if not is_active_actor(actor):
        raise PermissionDenied("Действие доступно только активному пользователю.")
    actor = get_user_model().objects.select_for_update().filter(pk=actor.pk, is_active=True).first()
    if actor is None or not is_active_actor(actor):
        raise PermissionDenied("Действие доступно только активному пользователю.")
    file_object = (
        MemoryFileObject.objects
        .select_related("source", "current_version", "current_version__source_object", "current_physical_placement")
        .filter(pk=file_object_id)
        .first()
    )
    if file_object is None:
        raise ValidationError("Файл не найден.")
    # Shared source lock serializes this write with source/access-sensitive
    # organization decisions and prevents a stale ACL snapshot.
    source = MemorySource.objects.select_for_update().get(pk=file_object.source_id)
    file_object = (
        MemoryFileObject.objects.select_for_update()
        .select_related("source", "current_version", "current_version__source_object", "current_physical_placement")
        .get(pk=file_object.pk)
    )
    if not can_access_file_object(actor, file_object):
        raise PermissionDenied("Недостаточно прав на файл.")
    normalized_path = normalize_relative_path(virtual_path)
    if not normalized_path:
        raise ValidationError("Укажите виртуальный путь.")
    view = (
        MemoryFileVirtualView.objects.select_for_update()
        .filter(
            source=file_object.source,
            view_kind=MemoryFileVirtualView.ViewKind.USER,
            slug=f"user-{actor.pk}",
        )
        .first()
    )
    if view is None:
        view = MemoryFileVirtualView.objects.create(
            source=file_object.source,
            view_kind=MemoryFileVirtualView.ViewKind.USER,
            slug=f"user-{actor.pk}",
            title=f"Личная структура {actor.get_username()}",
            owner_user=actor,
            status=MemoryFileVirtualView.Status.ACTIVE,
            is_system=False,
        )
    elif view.owner_user_id != actor.pk:
        raise PermissionDenied("Владелец пользовательского представления не может быть изменен.")
    placement = (
        MemoryFileVirtualPlacement.objects.select_for_update()
        .filter(view=view, file_object=file_object, virtual_path=normalized_path)
        .first()
    )
    defaults = {
        "placement_source": MemoryFileVirtualPlacement.PlacementSource.USER_MANUAL,
        "confidence": decimal_confidence(1.0),
        "status": MemoryFileVirtualPlacement.Status.ACCEPTED,
        "review_required": False,
        "evidence": ["user_manual"],
        "conflicts": [],
        "created_by": actor,
    }
    if placement is None:
        placement = MemoryFileVirtualPlacement.objects.create(
            view=view,
            file_object=file_object,
            virtual_path=normalized_path,
            **defaults,
        )
    else:
        for field, value in defaults.items():
            setattr(placement, field, value)
        placement.save(update_fields=[*defaults.keys(), "updated_at"])
    from .file_organization_stats import _record_file_usage_event_locked

    _record_file_usage_event_locked(
        source=file_object.source,
        event_kind=MemoryFileUsageEvent.EventKind.VIRTUAL_MOVE,
        file_object=file_object,
        view=view,
        actor=actor,
        virtual_path=normalized_path,
    )
    return placement


def get_or_create_system_view(
    *,
    source: MemorySource,
    view_kind: str,
    slug: str,
    title: str,
    baseline_profile: str = "",
    dry_run: bool = False,
) -> MemoryFileVirtualView | None:
    with exclusive_file_lock(access_control_write_lock_path(), timeout=300.0):
        with transaction.atomic():
            source = MemorySource.objects.select_for_update().get(pk=source.pk)
            require_enabled_file_source(source)
            return _get_or_create_system_view_locked(
                source=source,
                view_kind=view_kind,
                slug=slug,
                title=title,
                baseline_profile=baseline_profile,
                dry_run=dry_run,
            )


def _get_or_create_system_view_locked(
    *,
    source: MemorySource,
    view_kind: str,
    slug: str,
    title: str,
    baseline_profile: str = "",
    dry_run: bool = False,
) -> MemoryFileVirtualView | None:
    require_enabled_file_source(source)
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
    with exclusive_file_lock(access_control_write_lock_path(), timeout=300.0):
        with transaction.atomic():
            source = MemorySource.objects.select_for_update().get(pk=source.pk)
            require_enabled_file_source(source)
            return _create_file_organization_issue_locked(
                source=source,
                source_object=source_object,
                message=message,
                metadata=metadata,
                severity=severity,
                issue_kind=issue_kind,
            )


def _create_file_organization_issue_locked(
    *,
    source: MemorySource,
    source_object: MemorySourceObject | None,
    message: str,
    metadata: dict,
    severity=MemoryIngestionIssue.Severity.WARNING,
    issue_kind=MemoryIngestionIssue.IssueKind.CANONICALIZATION_CONFLICT,
) -> MemoryIngestionIssue:
    require_enabled_file_source(source)
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
