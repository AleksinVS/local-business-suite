from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.memory.models import MemorySource

from .file_organization import decimal_confidence, get_file_organization_profile, path_bucket, safe_path_hash
from .models import (
    MemoryFileOrganizationDecision,
    MemoryFileOrganizationProposal,
    MemoryFileUsageEvent,
    MemoryFileVirtualPlacement,
    MemoryFileVirtualView,
)


def record_file_usage_event(
    *,
    source: MemorySource,
    event_kind: str,
    file_object=None,
    view=None,
    actor=None,
    virtual_path: str = "",
    metadata: dict | None = None,
) -> MemoryFileUsageEvent:
    return MemoryFileUsageEvent.objects.create(
        source=source,
        file_object=file_object,
        view=view,
        actor=actor,
        event_kind=event_kind,
        safe_path_hash=safe_path_hash(virtual_path) if virtual_path else "",
        safe_path_bucket=path_bucket(virtual_path) if virtual_path else "",
        metadata=_safe_event_metadata(metadata or {}),
    )


def build_organization_proposals(
    *,
    source: MemorySource,
    dry_run: bool = False,
    require_enabled: bool = True,
) -> dict:
    profile = get_file_organization_profile(source, require_enabled=require_enabled)
    thresholds = profile.proposal_thresholds
    metrics = {
        "source_code": source.code,
        "profile_id": profile.profile_id,
        "candidate_buckets": 0,
        "proposals": 0,
        "below_threshold": 0,
        "dry_run": dry_run,
        "sample": [],
    }
    candidates = _usage_candidates(source)
    metrics["candidate_buckets"] = len(candidates)
    organization_view = None
    if not dry_run:
        organization_view, _created = MemoryFileVirtualView.objects.update_or_create(
            source=source,
            view_kind=MemoryFileVirtualView.ViewKind.ORGANIZATION_CANDIDATE,
            slug="organization_candidate_from_usage",
            defaults={
                "title": "Кандидат общей структуры из статистики",
                "status": MemoryFileVirtualView.Status.ACTIVE,
                "is_system": True,
                "generated_at": timezone.now(),
            },
        )
    for bucket, candidate in sorted(candidates.items()):
        confidence = _proposal_confidence(candidate)
        below_threshold = (
            candidate["user_count"] < thresholds.min_users
            or candidate["event_count"] < thresholds.min_events
            or candidate["file_count"] < thresholds.min_files
            or confidence < thresholds.min_confidence
        )
        if below_threshold:
            metrics["below_threshold"] += 1
            continue
        proposal_payload = {
            "bucket": bucket,
            "target_template": f"{bucket}/<год>/<имя файла>",
            "source": "usage_aggregation_v1",
        }
        safe_summary = {
            "bucket": bucket,
            "file_count": candidate["file_count"],
            "user_count": candidate["user_count"],
            "event_count": candidate["event_count"],
            "confidence": round(confidence, 4),
        }
        if len(metrics["sample"]) < 20:
            metrics["sample"].append(safe_summary)
        if dry_run:
            metrics["proposals"] += 1
            continue
        if _has_rejected_equivalent(source=source, proposed_rule=proposal_payload):
            metrics["below_threshold"] += 1
            continue
        with transaction.atomic():
            proposal, created = MemoryFileOrganizationProposal.objects.update_or_create(
                source=source,
                title=f"Общая структура: {bucket}",
                defaults={
                    "target_view": organization_view,
                    "proposed_rule": proposal_payload,
                    "summary": (
                        f"Предложение создано из агрегированной статистики: файлов {candidate['file_count']}, "
                        f"пользователей {candidate['user_count']}, событий {candidate['event_count']}."
                    ),
                    "status": MemoryFileOrganizationProposal.Status.PROPOSED,
                    "affected_file_count": candidate["file_count"],
                    "confidence": decimal_confidence(confidence),
                    "evidence": [
                        {"kind": "file_count", "value": candidate["file_count"]},
                        {"kind": "user_count", "value": candidate["user_count"]},
                        {"kind": "event_count", "value": candidate["event_count"]},
                    ],
                    "conflicts": [],
                    "metrics": safe_summary,
                    "metadata": {"created_by": "usage_aggregation_v1"},
                },
            )
            if created:
                metrics["proposals"] += 1
            else:
                metrics["proposals"] += 1
    return metrics


def apply_organization_proposal_decision(*, proposal: MemoryFileOrganizationProposal, actor, decision: str, comment: str = ""):
    before_state = {"status": proposal.status, "reviewed_by_id": proposal.reviewed_by_id}
    if decision == MemoryFileOrganizationDecision.Decision.ACCEPT_AS_VIRTUAL_RULE:
        proposal.status = MemoryFileOrganizationProposal.Status.ACCEPTED_VIRTUAL
    elif decision == MemoryFileOrganizationDecision.Decision.ACCEPT_FOR_PHYSICAL_MOVE:
        proposal.status = MemoryFileOrganizationProposal.Status.ACCEPTED_PHYSICAL
    elif decision == MemoryFileOrganizationDecision.Decision.REJECT:
        proposal.status = MemoryFileOrganizationProposal.Status.REJECTED
    elif decision == MemoryFileOrganizationDecision.Decision.NEEDS_MORE_DATA:
        proposal.status = MemoryFileOrganizationProposal.Status.NEEDS_MORE_DATA
    elif decision == MemoryFileOrganizationDecision.Decision.EDIT:
        proposal.status = MemoryFileOrganizationProposal.Status.PROPOSED
    else:
        raise ValueError(f"Unsupported organization proposal decision '{decision}'.")
    proposal.reviewed_by = actor
    proposal.reviewed_at = timezone.now()
    proposal.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
    after_state = {"status": proposal.status, "reviewed_by_id": proposal.reviewed_by_id}
    decision_record = MemoryFileOrganizationDecision.objects.create(
        proposal=proposal,
        actor=actor,
        decision=decision,
        before_state=before_state,
        after_state=after_state,
        safe_metadata={"proposal_id": str(proposal.proposal_id)},
        comment=comment,
    )
    record_file_usage_event(
        source=proposal.source,
        event_kind=MemoryFileUsageEvent.EventKind.PROPOSAL_DECISION,
        actor=actor,
        virtual_path=(proposal.proposed_rule or {}).get("target_template", ""),
        metadata={"proposal_id": str(proposal.proposal_id), "decision": decision},
    )
    return decision_record


def _usage_candidates(source: MemorySource) -> dict[str, dict]:
    candidates: dict[str, dict] = defaultdict(lambda: {"file_ids": set(), "actor_ids": set(), "event_count": 0})
    for placement in MemoryFileVirtualPlacement.objects.select_related("file_object", "view").filter(
        view__source=source,
        status__in=[MemoryFileVirtualPlacement.Status.PROPOSED, MemoryFileVirtualPlacement.Status.ACCEPTED],
    ):
        bucket = path_bucket(placement.virtual_path)
        if not bucket:
            continue
        candidates[bucket]["file_ids"].add(placement.file_object_id)
        if placement.created_by_id:
            candidates[bucket]["actor_ids"].add(placement.created_by_id)
    event_rows = (
        MemoryFileUsageEvent.objects.filter(source=source, safe_path_bucket__gt="")
        .values("safe_path_bucket")
        .annotate(
            event_count=Count("id"),
            user_count=Count("actor_id", distinct=True),
            file_count=Count("file_object_id", distinct=True),
        )
    )
    for row in event_rows:
        bucket = row["safe_path_bucket"]
        candidates[bucket]["event_count"] += row["event_count"]
        candidates[bucket]["user_count_from_events"] = row["user_count"]
        candidates[bucket]["file_count_from_events"] = row["file_count"]
    normalized = {}
    for bucket, data in candidates.items():
        normalized[bucket] = {
            "file_count": max(len(data["file_ids"]), data.get("file_count_from_events", 0)),
            "user_count": max(len(data["actor_ids"]), data.get("user_count_from_events", 0)),
            "event_count": data["event_count"],
        }
    return normalized


def _proposal_confidence(candidate: dict) -> float:
    file_score = min(candidate["file_count"] / 20, 0.35)
    user_score = min(candidate["user_count"] / 10, 0.3)
    event_score = min(candidate["event_count"] / 50, 0.25)
    return min(1.0, 0.2 + file_score + user_score + event_score)


def _has_rejected_equivalent(*, source: MemorySource, proposed_rule: dict) -> bool:
    return MemoryFileOrganizationProposal.objects.filter(
        source=source,
        status=MemoryFileOrganizationProposal.Status.REJECTED,
        proposed_rule=proposed_rule,
    ).exists()


def _safe_event_metadata(metadata: dict) -> dict:
    blocked_keys = {"raw_query", "raw_content", "full_path", "full_unc_path"}
    return {key: value for key, value in metadata.items() if key not in blocked_keys}
