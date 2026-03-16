from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView

from .forms import MedicalDeviceForm
from .models import MedicalDevice, OperationalStatus
from apps.workorders.policies import can_manage_inventory


class MedicalDeviceListView(LoginRequiredMixin, ListView):
    model = MedicalDevice
    template_name = "inventory/device_list.html"
    context_object_name = "devices"
    paginate_by = 20

    def get_queryset(self):
        queryset = MedicalDevice.objects.order_by("name", "serial_number")
        q = self.request.GET.get("q", "").strip()
        department = self.request.GET.get("department", "").strip()
        status_value = self.request.GET.get("operational_status", "").strip()

        if q:
            queryset = queryset.filter(
                Q(name__icontains=q)
                | Q(manufacturer__icontains=q)
                | Q(model__icontains=q)
                | Q(serial_number__icontains=q)
                | Q(inventory_number__icontains=q)
                | Q(location__icontains=q)
            )
        if department:
            queryset = queryset.filter(department__iexact=department)
        if status_value:
            queryset = queryset.filter(operational_status=status_value)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = OperationalStatus.choices
        context["departments"] = (
            MedicalDevice.objects.exclude(department="")
            .order_by("department")
            .values_list("department", flat=True)
            .distinct()
        )
        context["filters"] = {
            "q": self.request.GET.get("q", ""),
            "department": self.request.GET.get("department", ""),
            "operational_status": self.request.GET.get("operational_status", ""),
        }
        return context


class MedicalDeviceCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = MedicalDevice
    form_class = MedicalDeviceForm
    template_name = "inventory/device_form.html"
    success_url = reverse_lazy("inventory:list")

    def test_func(self):
        return can_manage_inventory(self.request.user)
