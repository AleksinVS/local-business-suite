from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.db.models import F
from django.views import View
from django.views.generic import TemplateView

from apps.memory.models import MemorySource
from apps.memory.policies import can_review_organization_memory, can_view_memory_review_queue, is_active_actor

from .file_organization import save_user_virtual_placement
from .file_organization_stats import apply_organization_proposal_decision
from .models import (
    MemoryFileMoveJob,
    MemoryFileObject,
    MemoryFileOrganizationDecision,
    MemoryFileOrganizationProposal,
    MemoryFileVirtualPlacement,
    MemoryFileVirtualView,
)
from .selectors import (
    can_access_file_object,
    can_access_source_for_organization,
    proposal_membership_is_visible,
    visible_file_objects,
)


class MemoryReviewAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return can_view_memory_review_queue(self.request.user)


class MemoryFileOrganizationView(MemoryReviewAccessMixin, TemplateView):
    template_name = "filehub/review/file_organization.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sources = [source for source in MemorySource.objects.order_by("code") if can_access_source_for_organization(self.request.user, source)]
        valid_proposals = [
            proposal
            for proposal in MemoryFileOrganizationProposal.objects.select_related("source", "reviewed_by").filter(source__in=sources)
            if proposal_membership_is_visible(self.request.user, proposal)
        ]
        valid_proposals_by_source = {}
        for proposal in valid_proposals:
            valid_proposals_by_source.setdefault(proposal.source_id, []).append(proposal)
        context["sources"] = [
            {
                "source": source,
                "file_count": MemoryFileObject.objects.filter(source=source).count(),
                "baseline_count": MemoryFileVirtualPlacement.objects.filter(
                    file_object__source=source,
                    view__source=F("file_object__source"),
                    view__view_kind="baseline_auto",
                ).count(),
                "proposal_count": len(valid_proposals_by_source.get(source.pk, [])),
                "move_job_count": MemoryFileMoveJob.objects.filter(
                    source=source,
                    file_object__source=source,
                ).count(),
            }
            for source in sources
        ]
        visible_file_ids = [file_object.pk for file_object in visible_file_objects(self.request.user)]
        context["placements"] = (
            MemoryFileVirtualPlacement.objects.select_related("view", "file_object", "view__source")
            .filter(file_object_id__in=visible_file_ids, view__source=F("file_object__source"))
            .order_by("-updated_at", "-id")[:50]
        )
        context["proposals"] = (
            valid_proposals[:50]
        )
        context["move_jobs"] = (
            MemoryFileMoveJob.objects.select_related("source", "file_object", "proposal")
            .filter(source__in=sources, file_object_id__in=visible_file_ids, file_object__source=F("source"))
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
                create_jobs=request.POST.get("create_jobs") == "1",
            )
        except (ValueError, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Решение по файловой структуре записано.")
        return redirect("filehub:file_organization")


class MemoryFileUserViewsView(LoginRequiredMixin, TemplateView):
    template_name = "filehub/files/user_views.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not is_active_actor(self.request.user):
            context["file_objects"] = []
            context["placements"] = MemoryFileVirtualPlacement.objects.none()
            context["user_views"] = MemoryFileVirtualView.objects.none()
            return context
        file_objects = [_file_object_display(file_object) for file_object in visible_file_objects(self.request.user)[:200]]
        visible_source_ids = {item["source_code"] for item in file_objects}
        user_views = MemoryFileVirtualView.objects.filter(
            owner_user=self.request.user,
            view_kind=MemoryFileVirtualView.ViewKind.USER,
            source__code__in=visible_source_ids,
            source__status=MemorySource.Status.ENABLED,
        ).order_by("source__code", "slug")
        context["file_objects"] = file_objects
        context["placements"] = (
            MemoryFileVirtualPlacement.objects.select_related("view", "file_object", "view__source")
            .filter(view__owner_user=self.request.user, view__view_kind=MemoryFileVirtualView.ViewKind.USER)
            .filter(view__source__status=MemorySource.Status.ENABLED, file_object__source__status=MemorySource.Status.ENABLED)
            .filter(file_object_id__in=[item["id"] for item in file_objects], view__source=F("file_object__source"))
            .order_by("virtual_path")
        )
        context["user_views"] = user_views
        return context

    def post(self, request):
        file_object = get_object_or_404(
            MemoryFileObject.objects.select_related("source", "current_version", "current_version__source_object"),
            pk=request.POST.get("file_object_id"),
        )
        if not can_access_file_object(request.user, file_object):
            raise PermissionDenied("Недостаточно прав на файл.")
        save_user_virtual_placement(
            actor=request.user,
            file_object_id=file_object.pk,
            virtual_path=request.POST.get("virtual_path", ""),
        )
        messages.success(request, "Виртуальное размещение сохранено.")
        return redirect("filehub:user_file_views")


def _file_object_display(file_object: MemoryFileObject) -> dict:
    placement = file_object.current_physical_placement
    return {
        "id": file_object.id,
        "file_id": file_object.file_id,
        "source_code": file_object.source.code,
        "path": placement.relative_path if placement is not None else file_object.file_id,
    }
