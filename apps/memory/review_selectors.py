from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db.models import Count, F, Q
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from .knowledge_files import recent_knowledge_commits_for_actor
from .models import (
    MemoryAccessAudit,
    MemoryExternalConnectorJob,
    MemoryIngestionIssue,
    MemoryKnowledgeItem,
    MemorySearchDocument,
    MemorySource,
    MemorySourceObject,
)
from .policies import (
    can_manage_memory_search_index,
    can_review_memory_issues,
    can_review_memory_privacy_issues,
    can_review_scoped_issue,
    can_review_scoped_search_document,
    can_access_search_document,
    can_view_memory_access_audit,
    can_view_memory_review_queue,
    resolve_active_actor,
    scope_tokens_match,
    source_scope_tokens,
    user_scope_tokens,
)
from .review_safety import safe_review_metadata, safe_review_text
from .services import can_access_source_object

OPEN_ISSUE_STATUSES = {
    MemoryIngestionIssue.Status.OPEN,
    MemoryIngestionIssue.Status.ACKNOWLEDGED,
    MemoryIngestionIssue.Status.NEEDS_EXPERT_REVIEW,
}
PRIVACY_ISSUE_KINDS = {
    MemoryIngestionIssue.IssueKind.PII_AUDIT,
    MemoryIngestionIssue.IssueKind.PII_BLOCKED,
    MemoryIngestionIssue.IssueKind.SECRET_BLOCKED,
}
INDEX_HEALTH_ISSUE_KINDS = {
    MemoryIngestionIssue.IssueKind.INDEX_FAILED,
    MemoryIngestionIssue.IssueKind.INDEX_STALE,
    MemoryIngestionIssue.IssueKind.FTS_MISSING,
    MemoryIngestionIssue.IssueKind.VECTOR_MISSING,
    MemoryIngestionIssue.IssueKind.SOURCE_DELETED_INDEX_LEFT,
}
INDEX_REVIEW_DISPLAY_LIMIT = 200
# JSONField arrays do not have a portable ``overlap`` lookup on all supported
# databases.  Keep the positional fallback deliberately large; ingestion
# validators reject unbounded scope lists, so this is a defensive upper bound
# rather than a silent first-16-elements policy.
SCOPE_TOKEN_FILTER_POSITION_LIMIT = 256


@dataclass(frozen=True)
class ReviewQueueItem:
    kind: str
    stable_key: str
    source_model: str
    source_pk: int | str
    severity: str
    status: str
    title: str
    safe_summary: str
    severity_label: str = ""
    status_label: str = ""
    source: str = ""
    target_type: str = ""
    target_type_label: str = ""
    target_id: str = ""
    assigned_to: str = ""
    created_at: Any = None
    updated_at: Any = None
    available_actions: tuple[str, ...] = field(default_factory=tuple)
    links: dict[str, str] = field(default_factory=dict)


def review_dashboard_context(user) -> dict[str, Any]:
    actor = resolve_active_actor(user, force_refresh=True)
    if actor is None or not can_view_memory_review_queue(actor):
        return _empty_dashboard()
    issue_queryset = _scoped_issue_queryset(_base_issue_queryset(), actor)
    document_queryset = _scoped_document_queryset(_base_document_queryset(), actor)
    return {
        "open_issue_count": issue_queryset.filter(status__in=OPEN_ISSUE_STATUSES).count(),
        "blocker_issue_count": issue_queryset.filter(severity=MemoryIngestionIssue.Severity.BLOCKER, status__in=OPEN_ISSUE_STATUSES).count(),
        "privacy_issue_count": issue_queryset.filter(issue_kind__in=PRIVACY_ISSUE_KINDS, status__in=OPEN_ISSUE_STATUSES).count(),
        "index_problem_count": _index_problem_count(document_queryset),
        "issue_counts_by_severity": _issue_severity_counts(issue_queryset),
        "document_counts_by_status": _document_status_counts(document_queryset),
        "recent_issues": [issue_to_review_queue_item(issue, user=actor) for issue in issue_queryset[:8]],
        "recent_jobs": list(_scoped_index_job_queryset(actor)[:8]),
    }


def review_issue_queryset(user, params=None):
    user = resolve_active_actor(user, force_refresh=True)
    queryset = _base_issue_queryset()
    if user is None or not can_view_memory_review_queue(user):
        return queryset.none()
    queryset = _scoped_issue_queryset(queryset, user)
    params = params or {}
    status = _param(params, "status")
    severity = _param(params, "severity")
    issue_kind = _param(params, "issue_kind")
    source_code = _param(params, "source")
    assigned = _param(params, "assigned")
    flag = _param(params, "flag")
    query = _param(params, "q")
    if status:
        queryset = queryset.filter(status=status)
    if severity:
        queryset = queryset.filter(severity=severity)
    if issue_kind:
        queryset = queryset.filter(issue_kind=issue_kind)
    if source_code:
        queryset = queryset.filter(source__code=source_code)
    if assigned == "me":
        queryset = queryset.filter(assigned_to=user)
    elif assigned == "none":
        queryset = queryset.filter(assigned_to__isnull=True)
    if flag == "privacy":
        queryset = queryset.filter(issue_kind__in=PRIVACY_ISSUE_KINDS)
    elif flag == "blocker":
        queryset = queryset.filter(severity=MemoryIngestionIssue.Severity.BLOCKER)
    elif flag == "index":
        queryset = queryset.filter(issue_kind__in=INDEX_HEALTH_ISSUE_KINDS)
    if query:
        queryset = queryset.filter(
            Q(message__icontains=query)
            | Q(source__code__icontains=query)
            | Q(source_object__relative_path__icontains=query)
            | Q(source_object__object_id__icontains=query)
        )
    return queryset


def issue_to_review_queue_item(issue: MemoryIngestionIssue, *, user) -> ReviewQueueItem:
    user = resolve_active_actor(user, force_refresh=True)
    if user is None or not can_review_scoped_issue(user, issue):
        raise PermissionDenied("Недоступная проблема памяти.")
    source_object = issue.source_object
    links = {"detail": reverse("memory:review_issue_detail", kwargs={"pk": issue.pk})}
    if source_object is not None:
        document = _document_for_source_object(source_object)
        if document is not None:
            links["search_document"] = reverse("memory:review_index_detail", kwargs={"document_id": document.document_id})
    return ReviewQueueItem(
        kind="issue",
        stable_key=f"issue:{issue.pk}",
        source_model="MemoryIngestionIssue",
        source_pk=issue.pk,
        severity=issue.severity,
        status=issue.status,
        title=issue.get_issue_kind_display(),
        safe_summary=safe_review_text(issue.message, max_length=220),
        severity_label=issue.get_severity_display(),
        status_label=issue.get_status_display(),
        source=issue.source.code if issue.source_id else "",
        target_type="source_object" if source_object is not None else "source",
        target_type_label="Объект источника" if source_object is not None else "Источник",
        target_id=source_object.relative_path if source_object is not None else issue.source.code,
        assigned_to=str(issue.assigned_to) if issue.assigned_to_id else "",
        created_at=issue.created_at,
        updated_at=issue.updated_at,
        available_actions=issue_available_actions(issue, user=user),
        links=links,
    )


def issue_detail_context(issue: MemoryIngestionIssue, *, user) -> dict[str, Any]:
    user = resolve_active_actor(user, force_refresh=True)
    if user is None or not can_review_scoped_issue(user, issue):
        raise PermissionDenied("Недоступная проблема памяти.")
    document = _document_for_source_object(issue.source_object) if issue.source_object_id else None
    access_audits = []
    if document is not None and can_view_memory_access_audit(user):
        access_audits = [
            audit
            for audit in MemoryAccessAudit.objects.order_by("-created_at", "-id")[:100]
            if document.document_id in (audit.returned_document_ids or [])
            and _audit_visible_to_actor(audit, document=document, user=user)
        ][:8]
    return {
        "issue": issue,
        "queue_item": issue_to_review_queue_item(issue, user=user),
        "safe_metadata": safe_review_metadata(issue.metadata or {}),
        "search_document": document,
        "review_log": list(reversed((issue.metadata or {}).get("review_log") or []))[:50],
        "access_audits": access_audits,
        "available_actions": issue_available_actions(issue, user=user),
    }


def issue_available_actions(issue: MemoryIngestionIssue, *, user) -> tuple[str, ...]:
    user = resolve_active_actor(user, force_refresh=True)
    if user is None or not can_review_scoped_issue(user, issue):
        return ()
    actions = []
    if can_review_memory_issues(user):
        actions.extend(["acknowledge", "assign", "request_expert_review", "comment"])
        if issue.status in {MemoryIngestionIssue.Status.RESOLVED, MemoryIngestionIssue.Status.IGNORED}:
            actions.append("reopen")
        else:
            actions.extend(["resolve", "ignore"])
    if issue.issue_kind in PRIVACY_ISSUE_KINDS and not can_review_memory_privacy_issues(user):
        actions = [action for action in actions if action in {"acknowledge", "comment"}]
    if can_manage_memory_search_index(user) and issue.source_object_id:
        actions.append("enqueue_reindex")
    return tuple(dict.fromkeys(actions))


def assignees_for_issue(issue: MemoryIngestionIssue, *, actor):
    """Return only active operators who can actually work on this issue."""
    from .policies import can_review_memory_issues, can_review_memory_privacy_issues

    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None or not can_view_memory_review_queue(actor) or not can_review_scoped_issue(actor, issue):
        return []
    candidates = get_user_model().objects.filter(is_active=True).prefetch_related("groups").order_by("username")
    result = []
    for assignee in candidates:
        if not can_review_memory_issues(assignee):
            continue
        if issue.issue_kind in PRIVACY_ISSUE_KINDS and not can_review_memory_privacy_issues(assignee):
            continue
        if can_review_scoped_issue(assignee, issue):
            result.append(assignee)
    return result


def index_document_queryset(user, params=None):
    user = resolve_active_actor(user, force_refresh=True)
    queryset = _base_document_queryset()
    if user is None or not can_view_memory_review_queue(user):
        return queryset.none()
    queryset = _scoped_document_queryset(queryset, user)
    params = params or {}
    corpus_type = _param(params, "corpus_type")
    object_kind = _param(params, "object_kind")
    index_status = _param(params, "index_status")
    source_code = _param(params, "source")
    gap = _param(params, "gap")
    query = _param(params, "q")
    if corpus_type:
        queryset = queryset.filter(corpus_type=corpus_type)
    if object_kind:
        queryset = queryset.filter(object_kind=object_kind)
    if index_status:
        queryset = queryset.filter(index_status=index_status)
    if source_code:
        queryset = queryset.filter(Q(source_object__source__code=source_code) | Q(knowledge_item__source_code=source_code))
    if query:
        queryset = queryset.filter(
            Q(document_id__icontains=query)
            | Q(source_object__relative_path__icontains=query)
            | Q(source_object__object_id__icontains=query)
            | Q(knowledge_item__memory_id__icontains=query)
        )
    if gap:
        scan_limit = INDEX_REVIEW_DISPLAY_LIMIT + 1
        return [document for document in queryset[:scan_limit] if gap in index_gap_flags(document)]
    return queryset


def search_document_to_review_queue_item(document: MemorySearchDocument, *, user) -> ReviewQueueItem:
    user = resolve_active_actor(user, force_refresh=True)
    if user is None or not can_review_scoped_search_document(user, document):
        raise PermissionDenied("Недоступный поисковый документ.")
    diagnostics = index_diagnostics(document)
    target = document_target_display(document)
    return ReviewQueueItem(
        kind="index_document",
        stable_key=f"search_document:{document.document_id}",
        source_model="MemorySearchDocument",
        source_pk=document.pk,
        severity=diagnostics["severity"],
        status=document.index_status,
        title=document.document_id,
        safe_summary=", ".join(diagnostics["stale_reasons"] or ["Метаданные индекса актуальны для MVP"]),
        severity_label=diagnostics["severity_label"],
        status_label=document.get_index_status_display(),
        source=document_source_code(document),
        target_type=document.object_kind,
        target_type_label=document.get_object_kind_display(),
        target_id=target,
        created_at=document.created_at,
        updated_at=document.updated_at,
        available_actions=index_available_actions(document, user=user),
        links={"detail": reverse("memory:review_index_detail", kwargs={"document_id": document.document_id})},
    )


def search_document_detail_context(document: MemorySearchDocument, *, user) -> dict[str, Any]:
    user = resolve_active_actor(user, force_refresh=True)
    if user is None or not can_review_scoped_search_document(user, document):
        raise PermissionDenied("Недоступный поисковый документ.")
    related_issues = MemoryIngestionIssue.objects.none()
    if document.source_object_id:
        related_issues = _base_issue_queryset().filter(source_object=document.source_object)
    access_audits = []
    if can_view_memory_access_audit(user):
        access_audits = [
            audit
            for audit in MemoryAccessAudit.objects.order_by("-created_at", "-id")[:100]
            if document.document_id in (audit.returned_document_ids or [])
            and _audit_visible_to_actor(audit, document=document, user=user)
        ][:12]
    return {
        "document": document,
        "queue_item": search_document_to_review_queue_item(document, user=user),
        "diagnostics": index_diagnostics(document),
        "safe_metadata": safe_review_metadata(document.metadata or {}),
        "related_issues": related_issues[:20],
        "review_log": list(reversed((document.metadata or {}).get("review_log") or []))[:50],
        "related_jobs": _jobs_for_document(document, user=user)[:20],
        "access_audits": access_audits,
        "available_actions": index_available_actions(document, user=user),
    }


def index_available_actions(document: MemorySearchDocument, *, user) -> tuple[str, ...]:
    user = resolve_active_actor(user, force_refresh=True)
    if user is None:
        return ()
    if not can_review_scoped_search_document(user, document):
        return ()
    if not can_manage_memory_search_index(user):
        return ()
    actions = ["dry_run_reindex", "enqueue_reindex"]
    if document.index_status == MemorySearchDocument.IndexStatus.FAILED:
        actions.append("retry_index")
    if index_stale_deletion_allowed(document):
        actions.append("delete_stale_index")
    return tuple(actions)


def index_stale_deletion_allowed(document: MemorySearchDocument) -> bool:
    return document.index_status in {
        MemorySearchDocument.IndexStatus.DELETED,
        MemorySearchDocument.IndexStatus.FAILED,
    } or bool(index_gap_flags(document))


def index_diagnostics(document: MemorySearchDocument) -> dict[str, Any]:
    metadata = document.metadata or {}
    versions = metadata.get("index_versions") or {}
    stale_reasons = []
    stale_reason_codes = []
    if document.index_status == MemorySearchDocument.IndexStatus.FAILED:
        stale_reasons.append("Статус индекса: ошибка")
        stale_reason_codes.append("index_status_failed")
    if document.index_status == MemorySearchDocument.IndexStatus.DELETED:
        stale_reasons.append("Документ помечен удаленным")
        stale_reason_codes.append("document_marked_deleted")
    if "fulltext" not in versions:
        stale_reasons.append("Нет версии FTS")
        stale_reason_codes.append("fts_version_missing")
    if "vector" not in versions:
        stale_reasons.append("Нет версии вектора")
        stale_reason_codes.append("vector_version_missing")
    if document.source_object_id:
        source_object = document.source_object
        if metadata.get("content_hash") and metadata.get("content_hash") != source_object.content_hash:
            stale_reasons.append("Хеш содержимого изменился")
            stale_reason_codes.append("content_hash_changed")
        if source_object.discovery_status == source_object.DiscoveryStatus.MISSING and document.index_status != MemorySearchDocument.IndexStatus.DELETED:
            stale_reasons.append("Объект источника отсутствует, но индекс активен")
            stale_reason_codes.append("source_object_missing_index_live")
    severity = "warning" if stale_reasons else "info"
    if document.index_status == MemorySearchDocument.IndexStatus.FAILED:
        severity = "error"
    fulltext_status = "ready" if versions.get("fulltext") else "missing"
    vector_status = "ready" if versions.get("vector") else "missing"
    return {
        "fulltext_status": fulltext_status,
        "fulltext_status_label": "Готов" if fulltext_status == "ready" else "Отсутствует",
        "vector_status": vector_status,
        "vector_status_label": "Готов" if vector_status == "ready" else "Отсутствует",
        "stale_reasons": stale_reasons,
        "stale_reason_codes": stale_reason_codes,
        "severity": severity,
        "severity_label": _severity_label(severity),
        "index_versions": versions,
    }


def index_gap_flags(document: MemorySearchDocument) -> set[str]:
    diagnostics = index_diagnostics(document)
    flags = set()
    if diagnostics["fulltext_status"] == "missing":
        flags.add("missing_fts")
    if diagnostics["vector_status"] == "missing":
        flags.add("missing_vector")
    if document.index_status == MemorySearchDocument.IndexStatus.FAILED:
        flags.add("failed")
    if document.index_status == MemorySearchDocument.IndexStatus.DELETED:
        flags.add("deleted")
    if "source_object_missing_index_live" in diagnostics["stale_reason_codes"]:
        flags.add("source_deleted_index_left")
    return flags


def review_audit_context(user, params=None) -> dict[str, Any]:
    """Combined audit feed (ADR-0030 decision 4): the issue queue's decided
    items, the unified queue's recent tasks, and git-derived commit history —
    replacing the removed per-click ``MemoryReviewAction`` log table."""
    user = resolve_active_actor(user, force_refresh=True)
    if user is None or not can_view_memory_review_queue(user):
        return {"decided_issues": [], "recent_jobs": [], "recent_commits": []}
    decided_issues = list(
        _scoped_issue_queryset(_base_issue_queryset(), user)
        .filter(status__in=[MemoryIngestionIssue.Status.RESOLVED, MemoryIngestionIssue.Status.IGNORED])
        .order_by("-updated_at", "-id")[:50]
    )
    recent_jobs = list(_scoped_index_job_queryset(user)[:50])
    recent_commits = recent_knowledge_commits_for_actor(actor=user, limit=50)
    return {
        "decided_issues": decided_issues,
        "recent_jobs": recent_jobs,
        "recent_commits": recent_commits,
    }


PENDING_REVIEW_DISPLAY_LIMIT = 200


def pending_knowledge_queryset(user, params=None):
    """Organization candidacy proposals and classification-downgrade holds
    (both surfaced as ``metadata.lifecycle == "pending"`` per ADR-0030
    decisions 4 & 8), scoped by the viewer's scope tokens."""
    user = resolve_active_actor(user, force_refresh=True)
    queryset = MemoryKnowledgeItem.objects.select_related("owner_user", "created_by").filter(
        metadata__lifecycle="pending"
    ).order_by("-updated_at", "-id")
    if user is None or not can_view_memory_review_queue(user):
        return queryset.none()
    if getattr(user, "is_superuser", False):
        return queryset
    tokens = sorted(user_scope_tokens(user))
    if not tokens:
        return queryset.none()
    return queryset.filter(_scope_token_overlap_q("scope_tokens", tokens))


def pending_item_kind(item: MemoryKnowledgeItem) -> str:
    return "candidate" if (item.metadata or {}).get("candidate_source_memory_id") else "downgrade"


def source_filter_options(user=None):
    user = resolve_active_actor(user, force_refresh=True) if user is not None else None
    queryset = MemorySource.objects.filter(status=MemorySource.Status.ENABLED).order_by("code")
    if user is None:
        return queryset.none().values_list("code", flat=True)
    if not getattr(user, "is_superuser", False):
        queryset = queryset.filter(pk__in=_visible_source_ids_for_user(user))
    return queryset.values_list("code", flat=True)


def document_target_display(document: MemorySearchDocument) -> str:
    if document.knowledge_item_id:
        return document.knowledge_item.memory_id
    if document.source_object_id:
        return document.source_object.relative_path or document.source_object.object_id
    return ""


def document_source_code(document: MemorySearchDocument) -> str:
    if document.source_object_id:
        return document.source_object.source.code
    if document.knowledge_item_id:
        return document.knowledge_item.source_code
    return ""


def _empty_dashboard() -> dict[str, Any]:
    return {
        "open_issue_count": 0,
        "blocker_issue_count": 0,
        "privacy_issue_count": 0,
        "index_problem_count": 0,
        "issue_counts_by_severity": [],
        "document_counts_by_status": [],
        "recent_issues": [],
        "recent_jobs": [],
    }


def _issue_severity_counts(queryset):
    rows = list(queryset.values("severity").annotate(total=Count("id")).order_by("severity"))
    labels = dict(MemoryIngestionIssue.Severity.choices)
    return [{**row, "label": labels.get(row["severity"], row["severity"])} for row in rows]


def _document_status_counts(queryset):
    rows = list(queryset.values("index_status").annotate(total=Count("id")).order_by("index_status"))
    labels = dict(MemorySearchDocument.IndexStatus.choices)
    return [{**row, "label": labels.get(row["index_status"], row["index_status"])} for row in rows]


def _severity_label(severity: str) -> str:
    return {
        "info": "Информация",
        "warning": "Предупреждение",
        "error": "Ошибка",
        "blocker": "Блокер",
    }.get(severity, severity)


def _base_issue_queryset():
    return MemoryIngestionIssue.objects.filter(source__status=MemorySource.Status.ENABLED).select_related("source", "source_object", "run").order_by(
        "status", "-created_at", "-id"
    )


def _base_document_queryset():
    return MemorySearchDocument.objects.filter(
        Q(source_object__isnull=True) | Q(source_object__source__status=MemorySource.Status.ENABLED)
    ).select_related(
        "knowledge_item",
        "source_object",
        "source_object__source",
    ).order_by("index_status", "corpus_type", "document_id")


def _scoped_issue_queryset(queryset, user):
    user = resolve_active_actor(user, force_refresh=True)
    if user is None:
        return queryset.none()
    if not user_scope_tokens(user):
        return queryset.none()
    source_ids = _visible_source_ids_for_user(user)
    scoped = queryset.filter(
        Q(source_object__isnull=False)
        | Q(source_object__isnull=True, source_id__in=source_ids)
    ).filter(Q(source_object__isnull=True) | Q(source_object__source_id=F("source_id")))
    return _filter_adapter_visible(scoped, user)


def _scoped_document_queryset(queryset, user):
    user = resolve_active_actor(user, force_refresh=True)
    if user is None:
        return queryset.none()
    tokens = sorted(user_scope_tokens(user))
    if not tokens:
        return queryset.none()
    knowledge_scope_q = _scope_token_overlap_q("knowledge_item__scope_tokens", tokens)
    scoped = queryset.filter(
        Q(source_object__isnull=False)
        | (Q(knowledge_item__isnull=False) & knowledge_scope_q)
    )
    return _filter_adapter_visible(scoped, user)


def _scoped_index_job_queryset(user):
    user = resolve_active_actor(user, force_refresh=True)
    queryset = MemoryExternalConnectorJob.objects.order_by("-created_at", "-id")
    if user is None:
        return queryset.none()
    if getattr(user, "is_superuser", False):
        enabled_codes = MemorySource.objects.filter(status=MemorySource.Status.ENABLED).values_list("code", flat=True)
        return queryset.exclude(source_code="").filter(source_code__in=enabled_codes)
    visible_codes = list(
        MemorySource.objects.filter(id__in=_visible_source_ids_for_user(user)).values_list("code", flat=True)
    )
    # Do not prefilter by the denormalized metadata token list: ACL fallback
    # and admin-only states are resolved by the object policy below.
    object_queryset = MemorySourceObject.objects.select_related("source")
    visible_objects = [
        source_object
        for source_object in object_queryset
        if can_access_source_object(user, source_object)
    ]
    # An empty source code is not a visible source: treating it as global
    # exposes jobs whose target cannot be scoped to the actor.
    visible_pairs = {(obj.source.code, str(obj.object_id)) for obj in visible_objects}
    visible_document_pairs = {
        (document.source_object.source.code, document.document_id)
        for document in MemorySearchDocument.objects.filter(
            source_object_id__in=[obj.pk for obj in visible_objects]
        ).select_related("source_object__source")
    }
    object_target_query = Q(pk__in=[])
    for source_code, object_id in visible_pairs:
        object_target_query |= Q(source_code=source_code, payload__source_object_id=object_id)
    for source_code, document_id in visible_document_pairs:
        object_target_query |= Q(source_code=source_code, payload__document_id=document_id)
    has_object_target = Q(payload__source_object_id__isnull=False) | Q(payload__document_id__isnull=False)
    source_wide_query = Q(source_code__in=visible_codes) & ~has_object_target
    return queryset.exclude(source_code="").filter(source_wide_query | object_target_query)


def _visible_source_ids_for_user(user) -> list[int]:
    user = resolve_active_actor(user, force_refresh=True)
    if user is None:
        return []
    if getattr(user, "is_superuser", False):
        return list(MemorySource.objects.filter(status=MemorySource.Status.ENABLED).values_list("id", flat=True))
    tokens = set(user_scope_tokens(user))
    if not tokens:
        return []
    source_ids = set()
    for source in MemorySource.objects.filter(status=MemorySource.Status.ENABLED).only("id", "status", "scope_rule", "config"):
        config = source.config or {}
        access_policy = config.get("access_policy") or {}
        # A single object passing adapter_check does not establish access to
        # the complete source.  Source-wide jobs/issues remain hidden unless
        # the source itself has a token scope (or the actor is superuser).
        if access_policy.get("mode") == "adapter_check":
            continue
        if scope_tokens_match(source_scope_tokens(source), tokens):
            source_ids.add(source.id)
    return sorted(source_ids)


def _filter_adapter_visible(queryset, user):
    """Apply the source adapter's final object-level check to a queryset."""
    user = resolve_active_actor(user, force_refresh=True)
    if user is None:
        return queryset.none()
    candidates = list(
        queryset.filter(source_object__isnull=False)
        .select_related("source_object", "source_object__source")
        .values_list("pk", "source_object")
    )
    if not candidates:
        return queryset
    visible_ids = []
    objects = MemorySourceObject.objects.select_related("source").filter(
        pk__in={source_object_id for _pk, source_object_id in candidates}
    )
    objects_by_id = {obj.pk: obj for obj in objects}
    for row_pk, source_object_id in candidates:
        source_object = objects_by_id.get(source_object_id)
        if source_object is not None and can_access_source_object(user, source_object):
            visible_ids.append(row_pk)
    return queryset.filter(Q(source_object__isnull=True) | Q(pk__in=visible_ids))


def _audit_visible_to_actor(audit, *, document, user) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    knowledge_item = getattr(document, "knowledge_item", None)
    if knowledge_item is not None and knowledge_item.scope == MemoryKnowledgeItem.Scope.PERSONAL:
        return knowledge_item.owner_user_id == getattr(user, "pk", None) or audit.actor_id == getattr(user, "pk", None)
    return bool(set(audit.allowed_scope_tokens or []) & set(user_scope_tokens(user)))


def _scope_token_overlap_q(path: str, tokens: list[str]) -> Q:
    if not tokens:
        return Q(pk__in=[])
    query = Q(pk__in=[])
    for position in range(SCOPE_TOKEN_FILTER_POSITION_LIMIT):
        query |= Q(**{f"{path}__{position}__in": tokens})
    return query


def _document_for_source_object(source_object):
    if source_object is None:
        return None
    return (
        MemorySearchDocument.objects.select_related("source_object", "source_object__source", "knowledge_item")
        .filter(source_object=source_object)
        .order_by("-indexed_at", "-updated_at", "-id")
        .first()
    )


def _jobs_for_document(document: MemorySearchDocument, *, user=None):
    user = resolve_active_actor(user, force_refresh=True)
    if user is None or not can_access_search_document(user, document):
        return MemoryExternalConnectorJob.objects.none()
    queryset = MemoryExternalConnectorJob.objects.order_by("-created_at", "-id")
    if document.source_object_id:
        result = queryset.filter(payload__document_id=document.document_id)
        if user is not None and getattr(user, "is_superuser", False):
            return result
        return result.filter(source_code=document.source_object.source.code)
    return queryset.filter(payload__document_id=document.document_id)


def _index_problem_count(queryset) -> int:
    return queryset.filter(
        Q(index_status__in=[MemorySearchDocument.IndexStatus.FAILED, MemorySearchDocument.IndexStatus.DELETED])
        | Q(metadata__index_versions__fulltext__isnull=True)
        | Q(metadata__index_versions__vector__isnull=True)
        | (Q(source_object__discovery_status=MemorySourceObject.DiscoveryStatus.MISSING) & ~Q(index_status=MemorySearchDocument.IndexStatus.DELETED))
    ).count()


def _param(params, name: str) -> str:
    value = params.get(name, "") if hasattr(params, "get") else ""
    return str(value or "").strip()
