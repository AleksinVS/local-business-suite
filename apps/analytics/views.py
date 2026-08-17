from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F
from django.views.generic import TemplateView

from apps.workorders.models import WorkOrderStatus
from apps.workorders.policies import can_view_analytics
from apps.workorders.selectors import (
    resolve_active_actor,
    visible_departments_queryset,
    visible_workorders_queryset,
)


class AnalyticsDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "analytics/dashboard.html"

    def test_func(self):
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        return actor is not None and can_view_analytics(actor)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Analytics is a read adapter over the same scoped workorder selector
        # used by the board and AI.  Aggregating the model directly leaks
        # branches for relational/department-scoped actors.
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        base_qs = visible_workorders_queryset(actor).select_related(
            "assignee"
        )
        status_labels = dict(WorkOrderStatus.choices)
        context["status_summary"] = [
            {
                "status": row["status"],
                "status_label": status_labels.get(row["status"], row["status"]),
                "total": row["total"],
            }
            for row in base_qs.values("status").annotate(total=Count("id")).order_by("status")
        ]
        department_rows = list(
            base_qs.values("department")
            .annotate(total=Count("id"))
            .order_by("-total", "department")
        )
        departments = visible_departments_queryset(actor)
        department_map = {department.id: department for department in departments}
        context["department_summary"] = [
            {
                "department_label": department_map[row["department"]].full_name,
                "total": row["total"],
            }
            for row in department_rows
            if row["department"] in department_map
        ]
        context["assignee_summary"] = list(
            base_qs.values("assignee__username", "assignee__first_name", "assignee__last_name")
            .annotate(total=Count("id"))
            .order_by("-total")
        )
        duration_qs = base_qs.filter(resolved_at__isnull=False).annotate(
            resolution_time=ExpressionWrapper(
                F("resolved_at") - F("created_at"),
                output_field=DurationField(),
            )
        )
        context["avg_resolution_time"] = duration_qs.aggregate(avg=Avg("resolution_time"))["avg"]
        context["closed_count"] = base_qs.filter(status=WorkOrderStatus.CLOSED).count()
        context["resolved_count"] = base_qs.filter(status=WorkOrderStatus.RESOLVED).count()
        return context
