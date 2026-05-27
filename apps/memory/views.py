from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView, TemplateView

from .models import MemoryIngestionIssue, MemoryReviewAction, MemorySearchDocument
from .policies import can_view_memory_review_queue
from .review_selectors import (
    INDEX_REVIEW_DISPLAY_LIMIT,
    index_document_queryset,
    issue_detail_context,
    review_actions_queryset,
    review_dashboard_context,
    review_issue_queryset,
    search_document_detail_context,
    search_document_to_review_queue_item,
    source_filter_options,
)
from .review_services import apply_index_review_action, apply_issue_review_action


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


class MemoryReviewAuditView(MemoryReviewAccessMixin, ListView):
    template_name = "memory/review/audit.html"
    context_object_name = "actions"
    paginate_by = 50

    def get_queryset(self):
        return review_actions_queryset(self.request.user, self.request.GET)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filters"] = self.request.GET
        context["action_choices"] = MemoryReviewAction.Action.choices
        context["decision_choices"] = MemoryReviewAction.Decision.choices
        return context
