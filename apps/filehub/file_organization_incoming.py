from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from django.utils import timezone

from apps.memory.document_ingestion import build_source_object_payload, get_source_ingestion_profile, resolve_source_root, sha256_file
from apps.memory.models import MemoryIngestionIssue, MemorySource, MemorySourceObject
from apps.memory.security import scan_for_secrets
from apps.memory.source_text_extraction import SUPPORTED_SOURCE_TEXT_EXTENSIONS

from .file_organization import (
    BASELINE_VIEW_SLUG,
    create_file_organization_issue,
    decimal_confidence,
    ensure_file_object_for_source_object,
    get_file_organization_profile,
    get_or_create_system_view,
    normalize_relative_path,
    stable_file_id_for_source_object,
)
from .file_organization_baseline import classify_baseline_placement
from .models import MemoryFileVirtualPlacement, MemoryFileVirtualView


def process_incoming_folder(
    *,
    source: MemorySource,
    dry_run: bool = False,
    limit: int | None = None,
    require_enabled: bool = True,
) -> dict:
    organization_profile = get_file_organization_profile(source, require_enabled=require_enabled)
    ingestion_profile = get_source_ingestion_profile(source)
    root = resolve_source_root(source)
    incoming_root = root / organization_profile.incoming_relative_path
    _ensure_incoming_dirs(incoming_root=incoming_root, dry_run=dry_run)
    metrics = {
        "source_code": source.code,
        "profile_id": organization_profile.profile_id,
        "incoming_path": organization_profile.incoming_relative_path,
        "seen": 0,
        "stable": 0,
        "created_or_updated": 0,
        "placements": 0,
        "review_required": 0,
        "blocked": 0,
        "skipped_unstable": 0,
        "issues": 0,
        "dry_run": dry_run,
    }
    if not incoming_root.exists():
        metrics["missing"] = True
        return metrics

    files = sorted(path for path in incoming_root.rglob("*") if path.is_file())
    if limit:
        files = files[:limit]
    now = timezone.now()
    view = get_or_create_system_view(
        source=source,
        view_kind=MemoryFileVirtualView.ViewKind.BASELINE_AUTO,
        slug=BASELINE_VIEW_SLUG,
        title="Исходная автоматическая структура",
        baseline_profile=organization_profile.baseline_profile,
        dry_run=dry_run,
    )
    for file_path in files:
        metrics["seen"] += 1
        if not _file_is_stable(file_path, stable_after_seconds=ingestion_profile.stable_after_seconds):
            metrics["skipped_unstable"] += 1
            continue
        metrics["stable"] += 1
        relative_path = normalize_relative_path(file_path.relative_to(root).as_posix())
        stat = file_path.stat()
        content_hash = sha256_file(file_path)
        object_id = _incoming_object_id(source=source, content_hash=content_hash, size_bytes=stat.st_size)
        source_object = MemorySourceObject(
            source=source,
            object_id=object_id,
            object_uri=str(file_path),
            relative_path=relative_path,
            file_name=file_path.name,
            extension=file_path.suffix.lower(),
            size_bytes=stat.st_size,
            mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
            content_hash=content_hash,
            last_seen_at=now,
            last_stable_at=now,
        )
        secret_blocked, secret_metadata = _incoming_secret_block(file_path)
        if dry_run:
            if secret_blocked:
                metrics["blocked"] += 1
                metrics["issues"] += 1
                continue
            file_id = stable_file_id_for_source_object(source_object)
            plan = classify_baseline_placement(source_object=source_object, file_id=file_id)
            metrics["placements"] += 1
            if plan.review_required:
                metrics["review_required"] += 1
            continue
        payload = build_source_object_payload(
            source=source,
            root=root,
            file_path=file_path,
            object_id=object_id,
            relative_path=relative_path,
            stat=stat,
            now=now,
            profile=ingestion_profile,
        )
        source_object, _created = MemorySourceObject.objects.update_or_create(
            source=source,
            object_id=object_id,
            defaults=payload,
        )
        metrics["created_or_updated"] += 1
        if secret_blocked:
            source_object.ingestion_status = MemorySourceObject.IngestionStatus.FAILED
            source_object.last_error = "Sensitive credential material was detected in incoming file."
            source_object.metadata = {**(source_object.metadata or {}), "incoming_secret_scan": secret_metadata}
            source_object.save(update_fields=["ingestion_status", "last_error", "metadata", "updated_at"])
            create_file_organization_issue(
                source=source,
                source_object=source_object,
                issue_kind=MemoryIngestionIssue.IssueKind.SECRET_BLOCKED,
                severity=MemoryIngestionIssue.Severity.BLOCKER,
                message="Входной файл заблокирован проверкой секретов.",
                metadata={"relative_path": relative_path, "secret_scan": secret_metadata},
            )
            metrics["blocked"] += 1
            metrics["issues"] += 1
            continue
        file_object = ensure_file_object_for_source_object(source_object)
        plan = classify_baseline_placement(source_object=source_object, file_id=file_object.file_id)
        placement_status = (
            MemoryFileVirtualPlacement.Status.NEEDS_REVIEW
            if plan.review_required
            else MemoryFileVirtualPlacement.Status.PROPOSED
        )
        MemoryFileVirtualPlacement.objects.update_or_create(
            view=view,
            file_object=file_object,
            virtual_path=plan.virtual_path,
            defaults={
                "placement_source": MemoryFileVirtualPlacement.PlacementSource.INCOMING_AUTO,
                "confidence": decimal_confidence(plan.confidence),
                "status": placement_status,
                "review_required": plan.review_required,
                "evidence": list(plan.evidence),
                "conflicts": list(plan.conflicts),
                "metadata": {
                    "source_object_id": source_object.object_id,
                    "relative_path": source_object.relative_path,
                    "incoming": True,
                },
            },
        )
        metrics["placements"] += 1
        if plan.review_required:
            metrics["review_required"] += 1
            create_file_organization_issue(
                source=source,
                source_object=source_object,
                severity=MemoryIngestionIssue.Severity.WARNING,
                message="Входной файл требует ревью перед публикацией размещения.",
                metadata={
                    "file_id": file_object.file_id,
                    "virtual_path": plan.virtual_path,
                    "confidence": plan.confidence,
                    "evidence": list(plan.evidence),
                    "conflicts": list(plan.conflicts),
                },
            )
            metrics["issues"] += 1
    return metrics


def _ensure_incoming_dirs(*, incoming_root: Path, dry_run: bool) -> None:
    if dry_run:
        return
    incoming_root.mkdir(parents=True, exist_ok=True)
    parent = incoming_root.parent
    for name in ("processing", "needs_review", "rejected"):
        (parent / name).mkdir(parents=True, exist_ok=True)


def _file_is_stable(path: Path, *, stable_after_seconds: int) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    return timezone.now().timestamp() - stat.st_mtime >= stable_after_seconds


def _incoming_object_id(*, source: MemorySource, content_hash: str, size_bytes: int) -> str:
    basis = f"{source.code}:incoming:{content_hash}:size:{size_bytes}"
    return "incoming:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:40]


def _incoming_secret_block(path: Path) -> tuple[bool, dict]:
    if path.suffix.lower() not in SUPPORTED_SOURCE_TEXT_EXTENSIONS:
        return False, {"checked": False, "reason": "unsupported_text_extension"}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return True, {"checked": True, "reason": str(exc), "findings": []}
    result = scan_for_secrets(text)
    return bool(result.blocked), result.as_dict()
