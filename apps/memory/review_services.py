from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .chat_memory import index_knowledge_item, rebuild_memory_projection
from .document_ingestion import delete_search_document_indexes
from .knowledge_files import _safe_repo_path, knowledge_repo_root, parse_knowledge_file, write_knowledge_item_file
from .models import MemoryIngestionIssue, MemoryKnowledgeItem, MemorySearchDocument
from .policies import (
    can_manage_memory_search_index,
    can_review_organization_memory,
    can_review_scoped_issue,
    can_review_scoped_search_document,
    can_review_memory_issues,
    can_review_memory_privacy_issues,
)
from .review_safety import safe_review_metadata, safe_review_text
from .review_selectors import PRIVACY_ISSUE_KINDS, index_stale_deletion_allowed
from .services import enqueue_memory_queue_task, MemoryQueueJobKind

# ADR-0030 decision 4: MemoryReviewAction (a per-click action-log table) is
# removed. Issue/index review actions now mutate the target row directly
# (status, assignment, resolution fields already on MemoryIngestionIssue; a
# bounded, safe-redacted ``review_log`` list in ``metadata`` otherwise), and
# git commits are the journal for knowledge revisions (candidacy accept/
# reject). These small plain choice classes replace
# ``MemoryReviewAction.Action``/``Decision`` without needing a model.
REVIEW_LOG_LIMIT = 20


class IssueReviewAction:
    ACKNOWLEDGE = "acknowledge"
    ASSIGN = "assign"
    REQUEST_EXPERT_REVIEW = "request_expert_review"
    RESOLVE = "resolve"
    IGNORE = "ignore"
    REOPEN = "reopen"
    COMMENT = "comment"
    ENQUEUE_REINDEX = "enqueue_reindex"


class IndexReviewAction:
    DRY_RUN_REINDEX = "dry_run_reindex"
    ENQUEUE_REINDEX = "enqueue_reindex"
    RETRY_INDEX = "retry_index"
    DELETE_STALE_INDEX = "delete_stale_index"


class ReviewDecision:
    APPLIED = "applied"
    QUEUED = "queued"
    INFO = "info"


@dataclass(frozen=True)
class ReviewActionOutcome:
    decision: str
    target: Any


@transaction.atomic
def apply_issue_review_action(*, actor, issue: MemoryIngestionIssue, action: str, payload=None) -> ReviewActionOutcome:
    payload = payload or {}
    _require_issue_action(actor, issue, action)
    comment = safe_review_text(payload.get("comment", ""), max_length=1000)
    decision = ReviewDecision.APPLIED

    if action == IssueReviewAction.ACKNOWLEDGE:
        issue.status = MemoryIngestionIssue.Status.ACKNOWLEDGED
    elif action == IssueReviewAction.REQUEST_EXPERT_REVIEW:
        issue.status = MemoryIngestionIssue.Status.NEEDS_EXPERT_REVIEW
    elif action == IssueReviewAction.RESOLVE:
        issue.status = MemoryIngestionIssue.Status.RESOLVED
        issue.resolved_at = timezone.now()
        issue.reviewed_by = actor
        issue.resolution_code = safe_review_text(payload.get("resolution_code", "resolved"), max_length=80)
        issue.resolution_note = comment
    elif action == IssueReviewAction.IGNORE:
        issue.status = MemoryIngestionIssue.Status.IGNORED
        issue.reviewed_by = actor
        issue.resolution_code = safe_review_text(payload.get("resolution_code", "ignored"), max_length=80)
        issue.resolution_note = comment
    elif action == IssueReviewAction.REOPEN:
        issue.status = MemoryIngestionIssue.Status.OPEN
        issue.resolved_at = None
        issue.reviewed_by = None
        issue.resolution_code = ""
        issue.resolution_note = ""
    elif action == IssueReviewAction.ASSIGN:
        issue.assigned_to = _resolve_assignee(payload.get("assigned_to"))
    elif action == IssueReviewAction.COMMENT:
        decision = ReviewDecision.INFO
    elif action == IssueReviewAction.ENQUEUE_REINDEX:
        if not can_manage_memory_search_index(actor):
            raise PermissionDenied("Управление поисковым индексом памяти недоступно.")
        _create_reindex_job_for_issue(actor=actor, issue=issue, dry_run=False)
        decision = ReviewDecision.QUEUED
    else:
        raise ValidationError(f"Неподдерживаемое действие ревью проблемы: {action}")

    _append_review_log(issue, action=action, decision=decision, actor=actor, comment=comment, extra=safe_review_metadata(payload))
    issue.save(
        update_fields=[
            "status",
            "assigned_to",
            "reviewed_by",
            "resolution_code",
            "resolution_note",
            "resolved_at",
            "metadata",
            "updated_at",
        ]
    )
    return ReviewActionOutcome(decision=decision, target=issue)


@transaction.atomic
def apply_index_review_action(*, actor, document: MemorySearchDocument, action: str, payload=None) -> ReviewActionOutcome:
    payload = payload or {}
    if not can_manage_memory_search_index(actor):
        raise PermissionDenied("Управление поисковым индексом памяти недоступно.")
    if not can_review_scoped_search_document(actor, document):
        raise PermissionDenied("Поисковый документ памяти вне текущей области ревью.")
    comment = safe_review_text(payload.get("comment", ""), max_length=1000)
    decision = ReviewDecision.APPLIED
    extra = safe_review_metadata(payload)

    if action == IndexReviewAction.DRY_RUN_REINDEX:
        decision = ReviewDecision.INFO
        extra = {**extra, "dry_run": _reindex_payload(document=document, dry_run=True)}
    elif action in {IndexReviewAction.ENQUEUE_REINDEX, IndexReviewAction.RETRY_INDEX}:
        _create_reindex_job_for_document(actor=actor, document=document, dry_run=False, retry=action == IndexReviewAction.RETRY_INDEX)
        decision = ReviewDecision.QUEUED
    elif action == IndexReviewAction.DELETE_STALE_INDEX:
        if not index_stale_deletion_allowed(document):
            raise ValidationError("Поисковый документ не устарел, не завершился ошибкой и не удален.")
        result = delete_search_document_indexes([document.document_id], index_backends=("fulltext", "vector"))
        if document.index_status != MemorySearchDocument.IndexStatus.DELETED:
            document.index_status = MemorySearchDocument.IndexStatus.DELETED
        extra = {**extra, "delete_result": result}
    else:
        raise ValidationError(f"Неподдерживаемое действие ревью индекса: {action}")

    _append_review_log(document, action=action, decision=decision, actor=actor, comment=comment, extra=extra)
    document.save(update_fields=["index_status", "metadata", "updated_at"])
    return ReviewActionOutcome(decision=decision, target=document)


def accept_pending_item(*, item: MemoryKnowledgeItem, actor) -> MemoryKnowledgeItem:
    """Owner acceptance of a pending knowledge page (ADR-0030 decisions 4 & 8).

    Applies whatever the file's frontmatter currently proposes (organization
    candidate content, or a classification change held by
    ``memory_reconcile``) to the projection, flips ``lifecycle`` back to
    ``current``, commits the merge (the git commit is the acceptance record;
    the actor is named in the commit message), and reindexes so the page
    becomes reachable through ``memory.search``.
    """
    if not can_review_organization_memory(actor):
        raise PermissionDenied("Ревью кандидатов памяти недоступно.")
    parsed = _read_pending_file(item)
    meta = parsed.metadata or {}

    item.sensitivity = str(meta.get("sensitivity") or item.sensitivity)
    item.scope_tokens = [str(token) for token in (meta.get("scope_tokens") or item.scope_tokens or [])]
    item.status = str(meta.get("status") or item.status)
    item.kind = str(meta.get("kind") or item.kind)
    updated_metadata = dict(item.metadata or {})
    updated_metadata["lifecycle"] = "current"
    updated_metadata.pop("pending_reason", None)
    updated_metadata["accepted_by"] = _actor_label(actor)
    updated_metadata["accepted_at"] = timezone.now().isoformat()
    item.metadata = updated_metadata
    item.save(update_fields=["sensitivity", "scope_tokens", "status", "kind", "metadata", "updated_at"])

    write_knowledge_item_file(
        item,
        body=parsed.body,
        commit_message=f"Accept pending knowledge {item.memory_id} (actor={_actor_label(actor)})",
    )
    rebuild_memory_projection(scope=item.scope, owner_user=item.owner_user)
    if item.status == MemoryKnowledgeItem.Status.ACTIVE:
        index_knowledge_item(item)
    return item


def reject_pending_item(*, item: MemoryKnowledgeItem, actor, reason: str = "") -> MemoryKnowledgeItem:
    """Reject a pending page. The decision is recorded as a git commit; the
    page is never indexed for search either way.

    A brand-new organization candidacy proposal is soft-deleted (``status`` ->
    ``deleted``; its text still survives in git history per ADR-0030 decision
    1). A classification downgrade held on an existing, previously-accepted
    item is reverted: the file's frontmatter is rewritten back to the item's
    still-current (higher) classification, so the file matches the approved
    state again.
    """
    if not can_review_organization_memory(actor):
        raise PermissionDenied("Ревью кандидатов памяти недоступно.")
    is_candidate = bool((item.metadata or {}).get("candidate_source_memory_id"))
    parsed = _read_pending_file(item)

    updated_metadata = dict(item.metadata or {})
    updated_metadata.pop("pending_reason", None)
    updated_metadata["rejected_by"] = _actor_label(actor)
    updated_metadata["rejected_at"] = timezone.now().isoformat()
    if reason:
        updated_metadata["rejection_reason"] = safe_review_text(reason, max_length=500)
    update_fields = ["metadata", "updated_at"]
    if is_candidate:
        updated_metadata["lifecycle"] = "rejected"
        item.status = MemoryKnowledgeItem.Status.DELETED
        update_fields.append("status")
        commit_verb = "Reject organization candidate"
    else:
        updated_metadata["lifecycle"] = "current"
        commit_verb = "Reject pending classification change for"
    item.metadata = updated_metadata
    item.save(update_fields=update_fields)

    write_knowledge_item_file(
        item,
        body=parsed.body,
        commit_message=f"{commit_verb} {item.memory_id} (actor={_actor_label(actor)})",
    )
    rebuild_memory_projection(scope=item.scope, owner_user=item.owner_user)
    return item


def _read_pending_file(item: MemoryKnowledgeItem):
    """Read the raw knowledge file for a pending item, bypassing the
    hash-validated read path: by definition the pending file's frontmatter
    (the proposal) has not yet been applied to the projection, so it will not
    match the projection's stored hashes while the migration-window
    authoritative flag is off."""
    if not item.knowledge_file_path:
        raise ValidationError(f"Knowledge item {item.memory_id} has no knowledge file path.")
    path = _safe_repo_path(knowledge_repo_root(), item.knowledge_file_path)
    if not path.exists():
        raise ValidationError(f"Knowledge file for {item.memory_id} is missing.")
    return parse_knowledge_file(path.read_text(encoding="utf-8"))


def _actor_label(actor) -> str:
    return getattr(actor, "username", "") or str(actor)


def _append_review_log(target, *, action: str, decision: str, actor, comment: str = "", extra=None) -> None:
    """Append a bounded, safe-redacted entry to ``target.metadata['review_log']``.

    Replaces the removed ``MemoryReviewAction`` table: the operational
    triage trail for an issue or search document now lives directly on that
    row's own ``metadata`` field (as the packet's design instructs), not in a
    separate audit table. Mutates ``target.metadata`` in place; the caller is
    responsible for including ``metadata`` in its ``save(update_fields=...)``.
    """
    metadata = dict(target.metadata or {})
    log = list(metadata.get("review_log") or [])
    entry = {
        "at": timezone.now().isoformat(),
        "actor": _actor_label(actor),
        "action": action,
        "decision": decision,
        "comment": comment,
    }
    if extra:
        entry["context"] = extra
    log.append(entry)
    metadata["review_log"] = log[-REVIEW_LOG_LIMIT:]
    target.metadata = metadata


def _require_issue_action(actor, issue: MemoryIngestionIssue, action: str) -> None:
    if not can_review_scoped_issue(actor, issue):
        raise PermissionDenied("Проблема памяти вне текущей области ревью.")
    if action == IssueReviewAction.ENQUEUE_REINDEX:
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
    return enqueue_memory_queue_task(
        job_kind=MemoryQueueJobKind.REINDEX,
        source_code=issue.source.code if issue.source_id else "",
        request_id=f"memory-review-issue-{issue.pk}",
        idempotency_key=f"memory-review-issue-{issue.pk}-{uuid.uuid4().hex[:12]}",
        payload={
            "mode": "memory_review_issue",
            "dry_run": dry_run,
            "issue_id": issue.pk,
            "source_object_id": issue.source_object.object_id,
            "document_id": _document_id_for_issue(issue),
            "secret_blocked_requires_source_fix": issue.issue_kind == MemoryIngestionIssue.IssueKind.SECRET_BLOCKED,
            "actor_id": getattr(actor, "id", None),
        },
    )


def _create_reindex_job_for_document(*, actor, document: MemorySearchDocument, dry_run: bool, retry: bool = False):
    return enqueue_memory_queue_task(
        job_kind=MemoryQueueJobKind.REINDEX,
        source_code=document.source_object.source.code if document.source_object_id else "",
        request_id=f"memory-review-document-{document.pk}",
        idempotency_key=f"memory-review-document-{document.pk}-{uuid.uuid4().hex[:12]}",
        payload={**_reindex_payload(document=document, dry_run=dry_run, retry=retry), "actor_id": getattr(actor, "id", None)},
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
