from __future__ import annotations

from collections import defaultdict
import hashlib
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.memory.models import MemorySource
from apps.memory.policies import can_review_organization_memory, can_view_memory_review_queue, is_active_actor
from apps.core.file_locks import (
    FileLockTimeoutError,
    access_control_write_lock_path,
    exclusive_file_lock,
    memory_source_lifecycle_lock_path,
)

from .file_organization import (
    decimal_confidence,
    get_file_organization_profile,
    path_bucket,
    require_enabled_file_source,
    safe_path_hash,
)
from .models import (
    MemoryFileObject,
    MemoryFileOrganizationDecision,
    MemoryFileOrganizationProposal,
    MemoryFileUsageEvent,
    MemoryFileVirtualPlacement,
    MemoryFileVirtualView,
)
from .selectors import can_access_source_for_organization
from .selectors import can_access_file_object


# Canonical database lock order: actor -> source -> proposal -> files (id)
# -> jobs (id) -> placements.  Preliminary foreign-key reads stay unlocked.


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
    """Public actor-aware usage writer; system pipelines use the private helper."""
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            with exclusive_file_lock(memory_source_lifecycle_lock_path(), timeout=10.0):
                with transaction.atomic():
                    return _record_file_usage_event_locked(
                        source=source,
                        event_kind=event_kind,
                        file_object=file_object,
                        view=view,
                        actor=actor,
                        virtual_path=virtual_path,
                        metadata=metadata,
                    )
    except FileLockTimeoutError as exc:
        raise ValidationError("Файловый контур занят. Повторите сохранение через несколько секунд.") from exc


def _record_file_usage_event_locked(
    *,
    source: MemorySource,
    event_kind: str,
    file_object=None,
    view=None,
    actor=None,
    virtual_path: str = "",
    metadata: dict | None = None,
) -> MemoryFileUsageEvent:
    if actor is None:
        raise PermissionDenied("Событие использования требует активного автора.")
    actor = _lock_active_actor(actor)
    source = MemorySource.objects.select_for_update().get(pk=source.pk)
    require_enabled_file_source(source)
    if file_object is not None:
        file_object = (
            MemoryFileObject.objects.select_for_update()
            .select_related("source", "current_version", "current_version__source_object", "current_physical_placement")
            .filter(pk=file_object.pk, source=source)
            .first()
        )
        if file_object is None:
            raise ValidationError("Файл события отсутствует или принадлежит другому источнику.")
    if view is not None:
        view = MemoryFileVirtualView.objects.select_for_update().filter(pk=view.pk, source=source).first()
        if view is None:
            raise ValidationError("Представление события отсутствует или принадлежит другому источнику.")
    if file_object is not None and file_object.source_id != source.pk:
        raise ValidationError("Файл события принадлежит другому источнику.")
    if view is not None and view.source_id != source.pk:
        raise ValidationError("Представление события принадлежит другому источнику.")
    if view is not None and view.view_kind == MemoryFileVirtualView.ViewKind.USER and actor is None:
        raise PermissionDenied("Пользовательское размещение требует активного автора.")
    if file_object is not None and not can_access_file_object(actor, file_object):
        raise PermissionDenied("Автор события не имеет текущего доступа к файлу.")
    if view is not None and view.view_kind == MemoryFileVirtualView.ViewKind.USER and view.owner_user_id != actor.pk:
        raise PermissionDenied("Автор не является владельцем пользовательского представления.")
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


def _record_system_usage_event_locked(*, source: MemorySource, event_kind: str, file_object=None, view=None, virtual_path: str = "", metadata=None):
    """Private trusted-pipeline writer; never exposed as an HTTP/service API."""
    if file_object is not None and file_object.source_id != source.pk:
        raise ValidationError("Файл системного события принадлежит другому источнику.")
    if view is not None and view.source_id != source.pk:
        raise ValidationError("Представление системного события принадлежит другому источнику.")
    return MemoryFileUsageEvent.objects.create(
        source=source,
        file_object=file_object,
        view=view,
        actor=None,
        event_kind=event_kind,
        safe_path_hash=safe_path_hash(virtual_path) if virtual_path else "",
        safe_path_bucket=path_bucket(virtual_path) if virtual_path else "",
        metadata=_safe_event_metadata({**(metadata or {}), "writer": "trusted_system_pipeline"}),
    )


def build_organization_proposals(
    *,
    source: MemorySource,
    dry_run: bool = False,
    require_enabled: bool = True,
) -> dict:
    if require_enabled is not True:
        raise ValueError("Обход проверки включенного источника запрещен.")
    with exclusive_file_lock(memory_source_lifecycle_lock_path(), timeout=300.0):
        with transaction.atomic():
            source = MemorySource.objects.select_for_update().get(pk=source.pk)
            return _build_organization_proposals_locked(source=source, dry_run=dry_run)


def _build_organization_proposals_locked(*, source: MemorySource, dry_run: bool = False) -> dict:
    profile = get_file_organization_profile(source)
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
            not candidate["file_ids"]
            or candidate["user_count"] < thresholds.min_users
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
            "file_ids": list(candidate["file_ids"]),
        }
        if len(metrics["sample"]) < 20:
            metrics["sample"].append(safe_summary)
        if dry_run:
            metrics["proposals"] += 1
            continue
        with transaction.atomic():
            locked_source = MemorySource.objects.select_for_update().get(pk=source.pk)
            base_title = f"Общая структура: {bucket}"
            proposal = (
                MemoryFileOrganizationProposal.objects.select_for_update()
                .filter(
                    source=locked_source,
                    title=base_title,
                    status=MemoryFileOrganizationProposal.Status.PROPOSED,
                )
                .order_by("-created_at", "-id")
                .first()
            )
            if proposal is None:
                version = MemoryFileOrganizationProposal.objects.filter(
                    source=locked_source,
                    title__startswith=base_title,
                ).count() + 1
                title = base_title if version == 1 else f"{base_title} [v{version}]"
                proposal = MemoryFileOrganizationProposal.objects.create(
                    source=locked_source,
                    title=title,
                    **{
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
                        "metadata": {
                            "created_by": "usage_aggregation_v1",
                            "file_ids": list(candidate["file_ids"]),
                            "membership_fingerprint": candidate["membership_fingerprint"],
                        },
                    },
                )
                created = True
            else:
                for field, value in {
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
                    "metadata": {
                        "created_by": "usage_aggregation_v1",
                        "file_ids": list(candidate["file_ids"]),
                        "membership_fingerprint": candidate["membership_fingerprint"],
                    },
                    "reviewed_by": None,
                    "reviewed_at": None,
                }.items():
                    setattr(proposal, field, value)
                proposal.save(update_fields=[
                    "target_view", "proposed_rule", "summary", "status", "affected_file_count",
                    "confidence", "evidence", "conflicts", "metrics", "metadata", "reviewed_by",
                    "reviewed_at", "updated_at",
                ])
                created = False
            metrics["proposals"] += 1
    return metrics


def apply_organization_proposal_decision(
    *,
    proposal: MemoryFileOrganizationProposal,
    actor,
    decision: str,
    comment: str = "",
    create_jobs: bool = False,
):
    try:
        with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
            with exclusive_file_lock(memory_source_lifecycle_lock_path(), timeout=10.0):
                with transaction.atomic():
                    return _apply_organization_proposal_decision_locked(
                        proposal=proposal,
                        actor=actor,
                        decision=decision,
                        comment=comment,
                        create_jobs=create_jobs,
                    )
    except FileLockTimeoutError as exc:
        raise ValidationError("Файловый контур занят. Повторите сохранение через несколько секунд.") from exc


def _apply_organization_proposal_decision_locked(
    *,
    proposal: MemoryFileOrganizationProposal,
    actor,
    decision: str,
    comment: str = "",
    create_jobs: bool = False,
):
    """Apply a decision and optional move jobs under one authorization lock."""

    actor = _lock_active_actor(actor)
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
    _require_decision_access(actor, proposal)
    # Source-wide review is available only for an enabled organization profile;
    # disabled sources require an explicit private reconciliation path.
    get_file_organization_profile(proposal.source, require_enabled=True)
    if proposal.status not in {
        MemoryFileOrganizationProposal.Status.PROPOSED,
        MemoryFileOrganizationProposal.Status.NEEDS_MORE_DATA,
    }:
        raise ValidationError("Предложение уже имеет окончательное решение или устарело.")
    previous_decision = proposal.decisions.order_by("-created_at", "-id").first()
    if previous_decision is not None and previous_decision.decision == decision:
        raise ValidationError("Повторное решение без изменения состояния не допускается.")
    if decision == MemoryFileOrganizationDecision.Decision.NEEDS_MORE_DATA and proposal.status == MemoryFileOrganizationProposal.Status.NEEDS_MORE_DATA:
        raise ValidationError("Предложение уже ожидает дополнительные данные.")
    if decision == MemoryFileOrganizationDecision.Decision.EDIT and proposal.status == MemoryFileOrganizationProposal.Status.PROPOSED:
        raise ValidationError("Предложение уже находится в состоянии редактирования.")
    approved_snapshot = None
    if decision == MemoryFileOrganizationDecision.Decision.ACCEPT_FOR_PHYSICAL_MOVE:
        approved_snapshot = _build_approved_snapshot(proposal)
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
        safe_metadata={"proposal_id": str(proposal.proposal_id), **({"approved_snapshot": approved_snapshot} if approved_snapshot else {})},
        comment=comment,
    )
    _record_file_usage_event_locked(
        source=proposal.source,
        event_kind=MemoryFileUsageEvent.EventKind.PROPOSAL_DECISION,
        actor=actor,
        virtual_path=(proposal.proposed_rule or {}).get("target_template", ""),
        metadata={"proposal_id": str(proposal.proposal_id), "decision": decision},
    )
    if create_jobs:
        if decision != MemoryFileOrganizationDecision.Decision.ACCEPT_FOR_PHYSICAL_MOVE:
            raise ValidationError("Задания можно создать только для физического переноса.")
        from .file_organization_move import _create_move_jobs_for_accepted_proposal_locked

        _create_move_jobs_for_accepted_proposal_locked(proposal=proposal, approved_by=actor)
    return decision_record


def _build_approved_snapshot(proposal: MemoryFileOrganizationProposal) -> dict:
    """Capture immutable physical-move membership and object/version evidence."""

    raw_ids = (proposal.metadata or {}).get("file_ids")
    if not isinstance(raw_ids, list):
        raise ValidationError("Физическое решение требует точный непустой список файлов.")
    file_ids = sorted({str(value).strip() for value in raw_ids or [] if str(value).strip()})
    if not file_ids or len(file_ids) != len(raw_ids or []):
        raise ValidationError("Физическое решение требует точный непустой список файлов.")
    if proposal.affected_file_count != len(file_ids):
        raise ValidationError("Количество файлов предложения не совпадает с точным списком.")
    expected_fingerprint = _membership_fingerprint(
        source=proposal.source,
        bucket=(proposal.proposed_rule or {}).get("bucket") or "",
        file_ids=file_ids,
    )
    if (proposal.metadata or {}).get("membership_fingerprint") != expected_fingerprint:
        raise ValidationError("Состав предложения устарел до принятия решения.")
    files = list(
        MemoryFileObject.objects.select_for_update()
        .select_related("current_version", "current_physical_placement")
        .filter(source=proposal.source, file_id__in=file_ids)
        .order_by("id")
    )
    if len(files) != len(file_ids) or {item.file_id for item in files} != set(file_ids):
        raise ValidationError("Состав физического решения содержит чужой или отсутствующий файл.")
    objects = []
    for file_object in files:
        version = file_object.current_version
        placement = file_object.current_physical_placement
        if version is None or placement is None or not placement.is_current or placement.source_object_id is None:
            raise ValidationError("Файл не имеет согласованной текущей версии и placement.")
        objects.append({
            "file_id": file_object.file_id,
            "file_object_id": file_object.pk,
            "version_id": version.pk,
            "sha256": version.sha256,
            "size_bytes": version.size_bytes,
            "source_placement_id": placement.pk,
        })
    return {
        "source_id": proposal.source_id,
        "source_code": proposal.source.code,
        "bucket": (proposal.proposed_rule or {}).get("bucket") or "",
        "file_ids": file_ids,
        "membership_fingerprint": (proposal.metadata or {}).get("membership_fingerprint", ""),
        "objects": objects,
    }


def _lock_active_actor(actor):
    if not is_active_actor(actor):
        raise PermissionDenied("Действие доступно только активному пользователю.")
    from django.contrib.auth import get_user_model

    current = get_user_model().objects.select_for_update().filter(pk=actor.pk, is_active=True).first()
    if current is None or not is_active_actor(current):
        raise PermissionDenied("Действие доступно только активному пользователю.")
    return current


def _fresh_active_actor(actor):
    if not is_active_actor(actor):
        raise PermissionDenied("Действие доступно только активному пользователю.")
    current = get_user_model().objects.filter(pk=actor.pk, is_active=True).first()
    if current is None or not is_active_actor(current):
        raise PermissionDenied("Действие доступно только активному пользователю.")
    return current


def _require_decision_access(actor, proposal):
    if not can_view_memory_review_queue(actor):
        raise PermissionDenied("Техническая группа ревью файловой структуры не назначена.")
    if not can_review_organization_memory(actor):
        raise PermissionDenied("Нет продуктового права на ревью общей структуры памяти.")
    if not can_access_source_for_organization(actor, proposal.source):
        raise PermissionDenied("Источник файлов находится вне текущей области доступа.")


def _usage_candidates(source: MemorySource) -> dict[str, dict]:
    candidates: dict[str, dict] = defaultdict(
        lambda: {"file_ids": set(), "actor_ids": set(), "event_count": 0, "invalid": False}
    )
    for placement in MemoryFileVirtualPlacement.objects.select_related("file_object", "view").filter(
        view__source=source,
        status__in=[MemoryFileVirtualPlacement.Status.PROPOSED, MemoryFileVirtualPlacement.Status.ACCEPTED],
    ):
        bucket = path_bucket(placement.virtual_path)
        if not bucket:
            continue
        if placement.file_object.source_id != source.pk or placement.view.source_id != source.pk:
            candidates[bucket]["invalid"] = True
            continue
        candidates[bucket]["file_ids"].add(placement.file_object.file_id)
        if placement.created_by_id:
            candidates[bucket]["actor_ids"].add(placement.created_by_id)
    for event in MemoryFileUsageEvent.objects.filter(source=source, safe_path_bucket__gt="").select_related("file_object", "view"):
        bucket = event.safe_path_bucket
        candidates[bucket]["event_count"] += 1
        if event.actor_id:
            candidates[bucket]["actor_ids"].add(event.actor_id)
        if event.view is not None and event.view.source_id != source.pk:
            candidates[bucket]["invalid"] = True
        if event.file_object_id:
            if event.file_object.source_id != source.pk:
                candidates[bucket]["invalid"] = True
            else:
                candidates[bucket]["file_ids"].add(event.file_object.file_id)
    normalized = {}
    for bucket, data in candidates.items():
        if data["invalid"]:
            continue
        file_ids = sorted(str(file_id) for file_id in data["file_ids"] if str(file_id).strip())
        normalized[bucket] = {
            "file_ids": file_ids,
            "file_count": len(file_ids),
            "user_count": len(data["actor_ids"]),
            "event_count": data["event_count"],
            "membership_fingerprint": _membership_fingerprint(source=source, bucket=bucket, file_ids=file_ids),
        }
    return normalized


def _proposal_confidence(candidate: dict) -> float:
    file_score = min(candidate["file_count"] / 20, 0.35)
    user_score = min(candidate["user_count"] / 10, 0.3)
    event_score = min(candidate["event_count"] / 50, 0.25)
    return min(1.0, 0.2 + file_score + user_score + event_score)


def _membership_fingerprint(*, source, bucket: str, file_ids: list[str]) -> str:
    payload = {"source": source.code, "bucket": bucket, "file_ids": sorted(file_ids)}
    return "sha256:" + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _has_rejected_equivalent(*, source: MemorySource, proposed_rule: dict) -> bool:
    return MemoryFileOrganizationProposal.objects.filter(
        source=source,
        status=MemoryFileOrganizationProposal.Status.REJECTED,
        proposed_rule=proposed_rule,
    ).exists()


def _safe_event_metadata(metadata: dict) -> dict:
    blocked_keys = {"raw_query", "raw_content", "full_path", "full_unc_path"}
    return {key: value for key, value in metadata.items() if key not in blocked_keys}
