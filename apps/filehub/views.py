from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import TemplateView

from apps.memory.models import MemorySearchDocument, MemorySource
from apps.memory.policies import (
    can_access_search_document,
    can_review_organization_memory,
    can_view_memory_review_queue,
    scope_tokens_match,
    user_scope_tokens,
)

from .file_organization import decimal_confidence, normalize_relative_path
from .file_organization_move import create_move_jobs_for_accepted_proposal
from .file_organization_stats import apply_organization_proposal_decision, record_file_usage_event
from .models import (
    MemoryFileMoveJob,
    MemoryFileObject,
    MemoryFileOrganizationDecision,
    MemoryFileOrganizationProposal,
    MemoryFileUsageEvent,
    MemoryFileVirtualPlacement,
    MemoryFileVirtualView,
)


class MemoryReviewAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_view_memory_review_queue(self.request.user)


class MemoryFileOrganizationView(MemoryReviewAccessMixin, TemplateView):
    template_name = "filehub/review/file_organization.html"

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
        return redirect("filehub:file_organization")


class MemoryFileUserViewsView(LoginRequiredMixin, TemplateView):
    template_name = "filehub/files/user_views.html"

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
            return redirect("filehub:user_file_views")
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
        return redirect("filehub:user_file_views")


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
