from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .document_ingestion import delete_search_document_indexes
from .models import MemoryIngestionIssue, MemoryIndexJob, MemoryReviewAction, MemorySearchDocument
from .policies import (
    can_manage_memory_search_index,
    can_review_scoped_issue,
    can_review_scoped_search_document,
    can_review_memory_issues,
    can_review_memory_privacy_issues,
)
from .review_safety import safe_review_metadata, safe_review_text
from .review_selectors import PRIVACY_ISSUE_KINDS, index_stale_deletion_allowed
from .services import create_index_job


@transaction.atomic
def apply_issue_review_action(*, actor, issue: MemoryIngestionIssue, action: str, payload=None) -> MemoryReviewAction:
    payload = payload or {}
    _require_issue_action(actor, issue, action)
    before_state = _issue_state(issue)
    comment = safe_review_text(payload.get("comment", ""), max_length=1000)
    decision = MemoryReviewAction.Decision.APPLIED
    index_job = None

    if action == MemoryReviewAction.Action.ACKNOWLEDGE:
        issue.status = MemoryIngestionIssue.Status.ACKNOWLEDGED
    elif action == MemoryReviewAction.Action.REQUEST_EXPERT_REVIEW:
        issue.status = MemoryIngestionIssue.Status.NEEDS_EXPERT_REVIEW
    elif action == MemoryReviewAction.Action.RESOLVE:
        issue.status = MemoryIngestionIssue.Status.RESOLVED
        issue.resolved_at = timezone.now()
        issue.reviewed_by = actor
        issue.resolution_code = safe_review_text(payload.get("resolution_code", "resolved"), max_length=80)
        issue.resolution_note = comment
    elif action == MemoryReviewAction.Action.IGNORE:
        issue.status = MemoryIngestionIssue.Status.IGNORED
        issue.reviewed_by = actor
        issue.resolution_code = safe_review_text(payload.get("resolution_code", "ignored"), max_length=80)
        issue.resolution_note = comment
    elif action == MemoryReviewAction.Action.REOPEN:
        issue.status = MemoryIngestionIssue.Status.OPEN
        issue.resolved_at = None
        issue.reviewed_by = None
        issue.resolution_code = ""
        issue.resolution_note = ""
    elif action == MemoryReviewAction.Action.ASSIGN:
        issue.assigned_to = _resolve_assignee(payload.get("assigned_to"))
    elif action == MemoryReviewAction.Action.COMMENT:
        decision = MemoryReviewAction.Decision.INFO
    elif action == MemoryReviewAction.Action.ENQUEUE_REINDEX:
        if not can_manage_memory_search_index(actor):
            raise PermissionDenied("Управление поисковым индексом памяти недоступно.")
        index_job = _create_reindex_job_for_issue(actor=actor, issue=issue, dry_run=False)
        decision = MemoryReviewAction.Decision.QUEUED
    else:
        raise ValidationError(f"Неподдерживаемое действие ревью проблемы: {action}")

    if action != MemoryReviewAction.Action.COMMENT:
        issue.save(
            update_fields=[
                "status",
                "assigned_to",
                "reviewed_by",
                "resolution_code",
                "resolution_note",
                "resolved_at",
                "updated_at",
            ]
        )
    return record_review_action(
        actor=actor,
        action=action,
        decision=decision,
        issue=issue,
        source_object=issue.source_object,
        index_job=index_job,
        before_state=before_state,
        after_state=_issue_state(issue),
        safe_metadata={"payload": safe_review_metadata(payload)},
        comment=comment,
    )


@transaction.atomic
def apply_index_review_action(*, actor, document: MemorySearchDocument, action: str, payload=None) -> MemoryReviewAction:
    payload = payload or {}
    if not can_manage_memory_search_index(actor):
        raise PermissionDenied("Управление поисковым индексом памяти недоступно.")
    if not can_review_scoped_search_document(actor, document):
        raise PermissionDenied("Поисковый документ памяти вне текущей области ревью.")
    before_state = _document_state(document)
    comment = safe_review_text(payload.get("comment", ""), max_length=1000)
    decision = MemoryReviewAction.Decision.APPLIED
    index_job = None
    safe_metadata = {"payload": safe_review_metadata(payload)}

    if action == MemoryReviewAction.Action.DRY_RUN_REINDEX:
        decision = MemoryReviewAction.Decision.INFO
        safe_metadata["dry_run"] = _reindex_payload(document=document, dry_run=True)
    elif action in {MemoryReviewAction.Action.ENQUEUE_REINDEX, MemoryReviewAction.Action.RETRY_INDEX}:
        index_job = _create_reindex_job_for_document(actor=actor, document=document, dry_run=False, retry=action == MemoryReviewAction.Action.RETRY_INDEX)
        decision = MemoryReviewAction.Decision.QUEUED
    elif action == MemoryReviewAction.Action.DELETE_STALE_INDEX:
        if not index_stale_deletion_allowed(document):
            raise ValidationError("Поисковый документ не устарел, не завершился ошибкой и не удален.")
        result = delete_search_document_indexes([document.document_id], index_backends=("fulltext", "vector"))
        if document.index_status != MemorySearchDocument.IndexStatus.DELETED:
            document.index_status = MemorySearchDocument.IndexStatus.DELETED
            metadata = dict(document.metadata or {})
            metadata["review_deleted_at"] = timezone.now().isoformat()
            metadata["review_deleted_by"] = getattr(actor, "username", "")
            document.metadata = metadata
            document.save(update_fields=["index_status", "metadata", "updated_at"])
        safe_metadata["delete_result"] = result
    else:
        raise ValidationError(f"Неподдерживаемое действие ревью индекса: {action}")

    return record_review_action(
        actor=actor,
        action=action,
        decision=decision,
        search_document=document,
        source_object=document.source_object,
        index_job=index_job,
        before_state=before_state,
        after_state=_document_state(document),
        safe_metadata=safe_metadata,
        comment=comment,
    )


def record_review_action(
    *,
    actor,
    action,
    decision,
    issue=None,
    search_document=None,
    source_object=None,
    index_job=None,
    access_audit=None,
    before_state=None,
    after_state=None,
    safe_metadata=None,
    comment="",
) -> MemoryReviewAction:
    return MemoryReviewAction.objects.create(
        actor=actor,
        action=action,
        decision=decision,
        issue=issue,
        search_document=search_document,
        source_object=source_object,
        index_job=index_job,
        access_audit=access_audit,
        before_state=safe_review_metadata(before_state or {}),
        after_state=safe_review_metadata(after_state or {}),
        safe_metadata=safe_review_metadata(safe_metadata or {}),
        comment=safe_review_text(comment, max_length=1000),
    )


def _require_issue_action(actor, issue: MemoryIngestionIssue, action: str) -> None:
    if not can_review_scoped_issue(actor, issue):
        raise PermissionDenied("Проблема памяти вне текущей области ревью.")
    if action == MemoryReviewAction.Action.ENQUEUE_REINDEX:
        if not can_manage_memory_search_index(actor):
            raise PermissionDenied("Управление поисковым индексом памяти недоступно.")
        return
    _require_issue_review(actor, issue)


def _require_issue_review(actor, issue: MemoryIngestionIssue) -> None:
    if issue.issue_kind in PRIVACY_ISSUE_KINDS:
        if not can_review_memory_privacy_issues(actor):
            raise PermissionDenied("Ревью проблем приватности памяти недоступно.")
        return
    if not can_review_memory_issues(actor):
        raise PermissionDenied("Ревью проблем памяти недоступно.")


def _resolve_assignee(value):
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    User = get_user_model()
    try:
        return User.objects.get(pk=int(raw_value))
    except (ValueError, User.DoesNotExist) as exc:
        raise ValidationError("Назначенный пользователь не существует.") from exc


def _create_reindex_job_for_issue(*, actor, issue: MemoryIngestionIssue, dry_run: bool):
    if issue.source_object_id is None:
        raise ValidationError("У проблемы нет объекта источника для переиндексации.")
    return create_index_job(
        job_kind=MemoryIndexJob.JobKind.REINDEX,
        source=issue.source,
        created_by=actor,
        request_id=f"memory-review-issue-{issue.pk}",
        payload={
            "mode": "memory_review_issue",
            "dry_run": dry_run,
            "issue_id": issue.pk,
            "source_object_id": issue.source_object.object_id,
            "document_id": _document_id_for_issue(issue),
            "secret_blocked_requires_source_fix": issue.issue_kind == MemoryIngestionIssue.IssueKind.SECRET_BLOCKED,
        },
    )


def _create_reindex_job_for_document(*, actor, document: MemorySearchDocument, dry_run: bool, retry: bool = False):
    return create_index_job(
        job_kind=MemoryIndexJob.JobKind.REINDEX,
        source=document.source_object.source if document.source_object_id else None,
        created_by=actor,
        request_id=f"memory-review-document-{document.pk}",
        payload=_reindex_payload(document=document, dry_run=dry_run, retry=retry),
    )


def _reindex_payload(*, document: MemorySearchDocument, dry_run: bool, retry: bool = False):
    return {
        "mode": "memory_review_document",
        "dry_run": dry_run,
        "retry": retry,
        "document_id": document.document_id,
        "corpus_type": document.corpus_type,
        "source_object_id": document.source_object.object_id if document.source_object_id else "",
        "knowledge_item_id": document.knowledge_item.memory_id if document.knowledge_item_id else "",
    }


def _document_id_for_issue(issue: MemoryIngestionIssue) -> str:
    if issue.source_object_id is None:
        return ""
    document = issue.source_object.search_documents.order_by("-indexed_at", "-updated_at", "-id").first()
    return document.document_id if document is not None else ""


def _issue_state(issue: MemoryIngestionIssue) -> dict:
    return {
        "id": issue.pk,
        "status": issue.status,
        "severity": issue.severity,
        "issue_kind": issue.issue_kind,
        "assigned_to_id": issue.assigned_to_id,
        "reviewed_by_id": issue.reviewed_by_id,
        "resolution_code": issue.resolution_code,
        "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else "",
    }


def _document_state(document: MemorySearchDocument) -> dict:
    return {
        "id": document.pk,
        "document_id": document.document_id,
        "corpus_type": document.corpus_type,
        "object_kind": document.object_kind,
        "index_status": document.index_status,
        "indexed_at": document.indexed_at.isoformat() if document.indexed_at else "",
        "body_hash": document.body_hash,
    }
