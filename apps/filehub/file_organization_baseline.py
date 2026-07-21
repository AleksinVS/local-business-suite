from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import transaction

from .file_organization import (
    BASELINE_VIEW_SLUG,
    create_file_organization_issue,
    decimal_confidence,
    ensure_file_object_for_source_object,
    get_file_organization_profile,
    get_or_create_system_view,
    sanitize_path_segment,
    sync_file_objects_from_source_objects,
)
from apps.memory.models import MemoryIngestionIssue, MemorySource, MemorySourceObject

from .models import MemoryFileVirtualPlacement, MemoryFileVirtualView


REVIEW_CONFIDENCE_THRESHOLD = 0.55


@dataclass(frozen=True)
class BaselinePlacementPlan:
    source_object: MemorySourceObject
    file_id: str
    virtual_path: str
    confidence: float
    evidence: tuple[str, ...]
    conflicts: tuple[str, ...]

    @property
    def review_required(self) -> bool:
        return self.confidence < REVIEW_CONFIDENCE_THRESHOLD or bool(self.conflicts)


def build_baseline_virtual_structure(
    *,
    source: MemorySource,
    dry_run: bool = False,
    limit: int | None = None,
    create_issues: bool = True,
    require_enabled: bool = True,
) -> dict:
    profile = get_file_organization_profile(source, require_enabled=require_enabled)
    sync_metrics = sync_file_objects_from_source_objects(source=source, dry_run=dry_run, limit=limit)
    queryset = MemorySourceObject.objects.filter(source=source).order_by("relative_path")
    if limit:
        queryset = queryset[:limit]

    view = get_or_create_system_view(
        source=source,
        view_kind=MemoryFileVirtualView.ViewKind.BASELINE_AUTO,
        slug=BASELINE_VIEW_SLUG,
        title="Исходная автоматическая структура",
        baseline_profile=profile.baseline_profile,
        dry_run=dry_run,
    )
    metrics = {
        "source_code": source.code,
        "profile_id": profile.profile_id,
        "seen": 0,
        "placements": 0,
        "review_required": 0,
        "issues": 0,
        "dry_run": dry_run,
        "sync": sync_metrics,
        "sample": [],
    }
    for source_object in queryset:
        metrics["seen"] += 1
        file_object = ensure_file_object_for_source_object(source_object) if not dry_run else None
        file_id = file_object.file_id if file_object is not None else _dry_run_file_id(source_object)
        plan = classify_baseline_placement(source_object=source_object, file_id=file_id)
        metrics["placements"] += 1
        if plan.review_required:
            metrics["review_required"] += 1
        if len(metrics["sample"]) < 20:
            metrics["sample"].append(_plan_as_safe_dict(plan))
        if dry_run:
            continue
        with transaction.atomic():
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
                    "placement_source": MemoryFileVirtualPlacement.PlacementSource.BASELINE_AUTO,
                    "confidence": decimal_confidence(plan.confidence),
                    "status": placement_status,
                    "review_required": plan.review_required,
                    "evidence": list(plan.evidence),
                    "conflicts": list(plan.conflicts),
                    "metadata": {
                        "source_object_id": source_object.object_id,
                        "relative_path": source_object.relative_path,
                        "baseline_profile": profile.baseline_profile,
                    },
                },
            )
            if create_issues and plan.review_required:
                issue_kind = (
                    MemoryIngestionIssue.IssueKind.ACL_UNRESOLVED
                    if "acl_scope_missing" in plan.conflicts
                    else MemoryIngestionIssue.IssueKind.CANONICALIZATION_CONFLICT
                )
                create_file_organization_issue(
                    source=source,
                    source_object=source_object,
                    issue_kind=issue_kind,
                    severity=MemoryIngestionIssue.Severity.WARNING,
                    message="Файл требует ревью перед принятием baseline-размещения.",
                    metadata={
                        "file_id": plan.file_id,
                        "virtual_path": plan.virtual_path,
                        "confidence": plan.confidence,
                        "evidence": list(plan.evidence),
                        "conflicts": list(plan.conflicts),
                    },
                )
                metrics["issues"] += 1
    return metrics


def classify_baseline_placement(*, source_object: MemorySourceObject, file_id: str) -> BaselinePlacementPlan:
    evidence: list[str] = []
    conflicts: list[str] = []
    confidence = 0.45
    file_name = sanitize_path_segment(source_object.file_name or source_object.relative_path, fallback=file_id)
    document_group, group_confidence, group_evidence = _document_group(source_object)
    evidence.extend(group_evidence)
    confidence += group_confidence
    year, year_evidence = _year_for_source_object(source_object)
    evidence.extend(year_evidence)
    if source_object.relative_path and "/" in source_object.relative_path:
        evidence.append("source_path_has_existing_group")
        confidence += 0.08
    if source_object.content_hash:
        evidence.append("content_hash_available")
        confidence += 0.08
    metadata = source_object.metadata or {}
    scope_tokens = metadata.get("scope_tokens") or []
    acl = metadata.get("acl") or {}
    if scope_tokens:
        evidence.append("scope_tokens_resolved")
        confidence += 0.07
    elif acl:
        conflicts.append("acl_scope_missing")
        confidence -= 0.15
    if source_object.source.sensitivity in {"secret", "pii_original"}:
        conflicts.append("sensitivity_requires_manual_review")
        confidence -= 0.2
    if not source_object.content_hash:
        conflicts.append("content_hash_missing")
        confidence -= 0.1
    confidence = max(0.0, min(1.0, confidence))
    virtual_path = "/".join(
        [
            sanitize_path_segment(document_group, fallback="Прочее"),
            str(year),
            file_name,
        ]
    )
    return BaselinePlacementPlan(
        source_object=source_object,
        file_id=file_id,
        virtual_path=virtual_path,
        confidence=confidence,
        evidence=tuple(evidence),
        conflicts=tuple(conflicts),
    )


def _document_group(source_object: MemorySourceObject) -> tuple[str, float, list[str]]:
    haystack = f"{source_object.relative_path} {source_object.file_name}".lower()
    extension = (source_object.extension or "").lower()
    rules = (
        (("договор", "contract", "agreement"), "Договоры", 0.24, "name_or_path_mentions_contract"),
        (("акт", "act", "acceptance"), "Финансы/Акты", 0.22, "name_or_path_mentions_act"),
        (("счет", "invoice", "bill"), "Финансы/Счета", 0.22, "name_or_path_mentions_invoice"),
        (("отчет", "report"), "Отчеты", 0.2, "name_or_path_mentions_report"),
        (("инструкц", "регламент", "procedure", "instruction", "manual"), "Регламенты", 0.2, "name_or_path_mentions_procedure"),
        (("письмо", "letter", "mail"), "Переписка", 0.16, "name_or_path_mentions_letter"),
    )
    for markers, group, score, evidence in rules:
        if any(marker in haystack for marker in markers):
            return group, score, [evidence]
    if extension in {".xls", ".xlsx", ".csv", ".tsv"}:
        return "Таблицы", 0.16, ["extension_is_table"]
    if extension in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return "Изображения", 0.14, ["extension_is_image"]
    if extension in {".pdf", ".doc", ".docx", ".txt", ".md"}:
        return "Документы", 0.12, ["extension_is_document"]
    return "Прочее", 0.0, ["no_document_group_signal"]


def _year_for_source_object(source_object: MemorySourceObject) -> tuple[int, list[str]]:
    path_text = f"{source_object.relative_path} {source_object.file_name}"
    match = re.search(r"\b(20\d{2}|19\d{2})\b", path_text)
    if match:
        return int(match.group(1)), ["path_or_name_contains_year"]
    if source_object.mtime:
        return source_object.mtime.year, ["mtime_year"]
    return 0, ["year_unknown"]


def _dry_run_file_id(source_object: MemorySourceObject) -> str:
    from .file_organization import stable_file_id_for_source_object

    return stable_file_id_for_source_object(source_object)


def _plan_as_safe_dict(plan: BaselinePlacementPlan) -> dict:
    return {
        "file_id": plan.file_id,
        "source_object_id": plan.source_object.object_id,
        "relative_path": plan.source_object.relative_path,
        "virtual_path": plan.virtual_path,
        "confidence": round(plan.confidence, 4),
        "evidence": list(plan.evidence),
        "conflicts": list(plan.conflicts),
        "review_required": plan.review_required,
    }
