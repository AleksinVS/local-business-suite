from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F
from django.views.generic import TemplateView

from apps.core.models import Department
from apps.workorders.models import WorkOrder, WorkOrderStatus
from apps.workorders.policies import can_manage_inventory


class AnalyticsDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "analytics/dashboard.html"

    def test_func(self):
        return can_manage_inventory(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base_qs = WorkOrder.objects.select_related("assignee")
        context["status_summary"] = list(
            base_qs.values("status").annotate(total=Count("id")).order_by("status")
        )
        department_rows = list(
            base_qs.values("department")
            .annotate(total=Count("id"))
            .order_by("-total", "department")
        )
        departments = Department.objects.select_related("parent")
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
