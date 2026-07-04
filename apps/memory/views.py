from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView, TemplateView

from .file_organization import decimal_confidence, normalize_relative_path
from .file_organization_move import create_move_jobs_for_accepted_proposal
from .file_organization_stats import apply_organization_proposal_decision
from .file_organization_stats import record_file_usage_event
from .models import (
    MemoryFileMoveJob,
    MemoryFileObject,
    MemoryFileOrganizationDecision,
    MemoryFileOrganizationProposal,
    MemoryFileUsageEvent,
    MemoryFileVirtualPlacement,
    MemoryFileVirtualView,
    MemoryIngestionIssue,
    MemorySearchDocument,
    MemorySource,
)
from .policies import (
    can_access_search_document,
    can_review_organization_memory,
    can_view_memory_review_queue,
    scope_tokens_match,
    user_scope_tokens,
)
from .review_selectors import (
    INDEX_REVIEW_DISPLAY_LIMIT,
    index_document_queryset,
    issue_detail_context,
    pending_item_kind,
    pending_knowledge_queryset,
    review_audit_context,
    review_dashboard_context,
    review_issue_queryset,
    search_document_detail_context,
    search_document_to_review_queue_item,
    source_filter_options,
)
from .review_services import (
    accept_pending_item,
    apply_index_review_action,
    apply_issue_review_action,
    reject_pending_item,
)


class MemoryReviewAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_view_memory_review_queue(self.request.user)


class MemoryReviewDashboardView(MemoryReviewAccessMixin, TemplateView):
    template_name = "memory/review/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(review_dashboard_context(self.request.user))
        return context


class MemoryIssueListView(MemoryReviewAccessMixin, ListView):
    template_name = "memory/review/issue_list.html"
    context_object_name = "issues"
    paginate_by = 50

    def get_queryset(self):
        return review_issue_queryset(self.request.user, self.request.GET)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filters"] = self.request.GET
        context["sources"] = source_filter_options(self.request.user)
        context["issue_statuses"] = MemoryIngestionIssue.Status.choices
        context["issue_severities"] = MemoryIngestionIssue.Severity.choices
        context["issue_kinds"] = MemoryIngestionIssue.IssueKind.choices
        return context


class MemoryIssueDetailView(MemoryReviewAccessMixin, TemplateView):
    template_name = "memory/review/issue_detail.html"

    def dispatch(self, request, *args, **kwargs):
        self.issue = get_object_or_404(review_issue_queryset(request.user), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(issue_detail_context(self.issue, user=self.request.user))
        context["assignees"] = get_user_model().objects.filter(is_active=True).order_by("username")
        return context


class MemoryIssueActionView(MemoryReviewAccessMixin, View):
    def post(self, request, pk):
        issue = get_object_or_404(review_issue_queryset(request.user), pk=pk)
        action = request.POST.get("action", "")
        try:
            apply_issue_review_action(actor=request.user, issue=issue, action=action, payload=request.POST)
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Действие по issue записано в журнал.")
        return redirect("memory:review_issue_detail", pk=issue.pk)


class MemoryIndexListView(MemoryReviewAccessMixin, TemplateView):
    template_name = "memory/review/index_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        documents = index_document_queryset(self.request.user, self.request.GET)
        display_documents = list(documents[: INDEX_REVIEW_DISPLAY_LIMIT + 1])
        context["documents"] = [
            search_document_to_review_queue_item(document, user=self.request.user)
            for document in display_documents[:INDEX_REVIEW_DISPLAY_LIMIT]
        ]
        context["filters"] = self.request.GET
        context["sources"] = source_filter_options(self.request.user)
        context["corpus_types"] = MemorySearchDocument.CorpusType.choices
        context["object_kinds"] = MemorySearchDocument.ObjectKind.choices
        context["index_statuses"] = MemorySearchDocument.IndexStatus.choices
        context["result_limited"] = len(display_documents) > INDEX_REVIEW_DISPLAY_LIMIT
        return context


class MemoryIndexDetailView(MemoryReviewAccessMixin, TemplateView):
    template_name = "memory/review/index_detail.html"

    def dispatch(self, request, *args, **kwargs):
        self.document = get_object_or_404(
            index_document_queryset(request.user),
            document_id=kwargs["document_id"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(search_document_detail_context(self.document, user=self.request.user))
        return context


class MemoryIndexActionView(MemoryReviewAccessMixin, View):
    def post(self, request, document_id):
        document = get_object_or_404(index_document_queryset(request.user), document_id=document_id)
        action = request.POST.get("action", "")
        try:
            apply_index_review_action(actor=request.user, document=document, action=action, payload=request.POST)
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Действие по индексу записано в журнал.")
        return redirect("memory:review_index_detail", document_id=document.document_id)


class MemoryReviewAuditView(MemoryReviewAccessMixin, TemplateView):
    """Combined audit feed (ADR-0030 decision 4): issue queue decisions,
    unified queue tasks, and git-derived commit history, replacing the
    removed ``MemoryReviewAction`` action log."""

    template_name = "memory/review/audit.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(review_audit_context(self.request.user))
        return context


class MemoryPendingListView(MemoryReviewAccessMixin, TemplateView):
    """Review UI for the git ``propose -> pending -> review -> stable``
    primitive (ADR-0030 decisions 4 & 8): organization candidacy proposals and
    classification-downgrade holds, replacing ``MemoryKnowledgeCandidate``."""

    template_name = "memory/review/pending_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = list(pending_knowledge_queryset(self.request.user))
        context["items"] = [{"item": item, "kind": pending_item_kind(item)} for item in items]
        context["can_decide_pending"] = can_review_organization_memory(self.request.user)
        return context


class MemoryPendingActionView(MemoryReviewAccessMixin, View):
    def post(self, request, memory_id):
        item = get_object_or_404(pending_knowledge_queryset(request.user), memory_id=memory_id)
        action = request.POST.get("action", "")
        try:
            if action == "accept":
                accept_pending_item(item=item, actor=request.user)
            elif action == "reject":
                reject_pending_item(item=item, actor=request.user, reason=request.POST.get("reason", ""))
            else:
                raise ValidationError(f"Unsupported pending action: {action}")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Решение по кандидату записано в git.")
        return redirect("memory:review_pending_list")


class MemoryFileOrganizationView(MemoryReviewAccessMixin, TemplateView):
    template_name = "memory/review/file_organization.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sources = MemorySource.objects.order_by("code")
        context["sources"] = [
            {
                "source": source,
                "file_count": MemoryFileObject.objects.filter(source=source).count(),
                "baseline_count": MemoryFileVirtualPlacement.objects.filter(
                    view__source=source,
                    view__view_kind="baseline_auto",
                ).count(),
                "proposal_count": MemoryFileOrganizationProposal.objects.filter(source=source).count(),
                "move_job_count": MemoryFileMoveJob.objects.filter(source=source).count(),
            }
            for source in sources
        ]
        context["placements"] = (
            MemoryFileVirtualPlacement.objects.select_related("view", "file_object", "view__source")
            .order_by("-updated_at", "-id")[:50]
        )
        context["proposals"] = (
            MemoryFileOrganizationProposal.objects.select_related("source", "reviewed_by")
            .order_by("status", "-created_at", "-id")[:50]
        )
        context["move_jobs"] = (
            MemoryFileMoveJob.objects.select_related("source", "file_object", "proposal")
            .order_by("status", "-created_at", "-id")[:50]
        )
        context["can_decide_file_organization"] = can_review_organization_memory(self.request.user)
        context["proposal_decisions"] = MemoryFileOrganizationDecision.Decision.choices
        return context


class MemoryFileOrganizationProposalActionView(MemoryReviewAccessMixin, View):
    def post(self, request, pk):
        if not can_review_organization_memory(request.user):
            raise PermissionDenied("Недостаточно прав для согласования файловой структуры.")
        proposal = get_object_or_404(MemoryFileOrganizationProposal, pk=pk)
        decision = request.POST.get("decision", "")
        comment = request.POST.get("comment", "")
        try:
            apply_organization_proposal_decision(
                proposal=proposal,
                actor=request.user,
                decision=decision,
                comment=comment,
            )
            if decision == MemoryFileOrganizationDecision.Decision.ACCEPT_FOR_PHYSICAL_MOVE and request.POST.get("create_jobs") == "1":
                create_move_jobs_for_accepted_proposal(proposal=proposal, approved_by=request.user)
        except (ValueError, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Решение по файловой структуре записано.")
        return redirect("memory:file_organization")


class MemoryFileUserViewsView(LoginRequiredMixin, TemplateView):
    template_name = "memory/files/user_views.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        file_objects = [
            _file_object_display(file_object)
            for file_object in MemoryFileObject.objects.select_related(
                "source",
                "current_physical_placement",
                "current_version",
                "current_version__source_object",
            ).order_by("source__code", "file_id")[:200]
            if _can_access_file_object(self.request.user, file_object)
        ]
        user_views = MemoryFileVirtualView.objects.filter(
            owner_user=self.request.user,
            view_kind=MemoryFileVirtualView.ViewKind.USER,
        ).order_by("source__code", "slug")
        context["file_objects"] = file_objects
        context["placements"] = (
            MemoryFileVirtualPlacement.objects.select_related("view", "file_object", "view__source")
            .filter(view__owner_user=self.request.user, view__view_kind=MemoryFileVirtualView.ViewKind.USER)
            .order_by("virtual_path")
        )
        context["user_views"] = user_views
        return context

    def post(self, request):
        file_object = get_object_or_404(
            MemoryFileObject.objects.select_related("source", "current_version", "current_version__source_object"),
            pk=request.POST.get("file_object_id"),
        )
        if not _can_access_file_object(request.user, file_object):
            raise PermissionDenied("Недостаточно прав на файл.")
        virtual_path = normalize_relative_path(request.POST.get("virtual_path", ""))
        if not virtual_path:
            messages.error(request, "Укажите виртуальный путь.")
            return redirect("memory:user_file_views")
        view, _created = MemoryFileVirtualView.objects.update_or_create(
            source=file_object.source,
            view_kind=MemoryFileVirtualView.ViewKind.USER,
            slug=f"user-{request.user.pk}",
            defaults={
                "title": f"Личная структура {request.user.get_username()}",
                "owner_user": request.user,
                "status": MemoryFileVirtualView.Status.ACTIVE,
                "is_system": False,
            },
        )
        MemoryFileVirtualPlacement.objects.update_or_create(
            view=view,
            file_object=file_object,
            virtual_path=virtual_path,
            defaults={
                "placement_source": MemoryFileVirtualPlacement.PlacementSource.USER_MANUAL,
                "confidence": decimal_confidence(1.0),
                "status": MemoryFileVirtualPlacement.Status.ACCEPTED,
                "review_required": False,
                "evidence": ["user_manual"],
                "conflicts": [],
                "created_by": request.user,
            },
        )
        record_file_usage_event(
            source=file_object.source,
            event_kind=MemoryFileUsageEvent.EventKind.VIRTUAL_MOVE,
            file_object=file_object,
            view=view,
            actor=request.user,
            virtual_path=virtual_path,
        )
        messages.success(request, "Виртуальное размещение сохранено.")
        return redirect("memory:user_file_views")


def _can_access_file_object(user, file_object: MemoryFileObject) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    source_object = getattr(getattr(file_object, "current_version", None), "source_object", None)
    if source_object is None:
        placement = file_object.physical_placements.select_related("source_object").filter(source_object__isnull=False).first()
        source_object = placement.source_object if placement is not None else None
    if source_object is None:
        return False
    document = MemorySearchDocument.objects.filter(source_object=source_object).first()
    if document is not None:
        return can_access_search_document(user, document)
    required_tokens = (source_object.metadata or {}).get("scope_tokens") or []
    if not required_tokens:
        acl = (source_object.metadata or {}).get("acl") or {}
        required_tokens = acl.get("scope_tokens") or []
    return scope_tokens_match(required_tokens, user_scope_tokens(user))


def _file_object_display(file_object: MemoryFileObject) -> dict:
    placement = file_object.current_physical_placement
    return {
        "id": file_object.id,
        "file_id": file_object.file_id,
        "source_code": file_object.source.code,
        "path": placement.relative_path if placement is not None else file_object.file_id,
    }
