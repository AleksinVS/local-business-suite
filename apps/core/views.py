from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from apps.inventory.models import MedicalDevice
from apps.workorders.models import WorkOrder, WorkOrderStatus


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["device_count"] = MedicalDevice.objects.count()
        context["open_workorder_count"] = WorkOrder.objects.exclude(
            status__in=[WorkOrderStatus.CLOSED, WorkOrderStatus.CANCELLED]
        ).count()
        context["status_counts"] = [
            {"label": label, "value": WorkOrder.objects.filter(status=status).count()}
            for status, label in WorkOrderStatus.choices
        ]
        context["recent_workorders"] = (
            WorkOrder.objects.select_related("device", "author", "assignee")
            .order_by("-created_at")[:8]
        )
        return context
