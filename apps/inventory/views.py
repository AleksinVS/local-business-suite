from collections import OrderedDict

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import MedicalDeviceForm
from .models import MedicalDevice, OperationalStatus
from .selectors import visible_departments_queryset, visible_devices_queryset
from .services import archive_device_command, create_device_command, update_device_command
from apps.workorders.policies import can_manage_inventory
from apps.workorders.selectors import resolve_active_actor


class MedicalDeviceListView(LoginRequiredMixin, ListView):
    model = MedicalDevice
    template_name = "inventory/device_list.html"
    context_object_name = "devices"
    # Группировка по подразделениям требует рендерить все отфильтрованные
    # изделия на одной странице, чтобы группы не «разрезались» пагинацией.
    paginator = None

    def get_queryset(self):
        archived = self.request.GET.get("archived", "").strip() == "1"
        queryset = visible_devices_queryset(
            self.request.user,
            include_archived=archived,
        )
        q = self.request.GET.get("q", "").strip()
        department = self.request.GET.get("department", "").strip()
        status_value = self.request.GET.get("operational_status", "").strip()

        if q:
            queryset = queryset.filter(
                Q(name__icontains=q)
                | Q(device_type__icontains=q)
                | Q(manufacturer__icontains=q)
                | Q(production_country__icontains=q)
                | Q(model__icontains=q)
                | Q(serial_number__icontains=q)
                | Q(inventory_number__icontains=q)
                | Q(registration_certificate_number__icontains=q)
                | Q(location__icontains=q)
                | Q(address__icontains=q)
            )
        if department:
            selected_department = visible_departments_queryset(self.request.user).filter(
                pk=department
            ).first()
            if selected_department:
                queryset = queryset.filter(department_id__in=selected_department.descendant_ids())
            else:
                queryset = queryset.none()
        if status_value:
            queryset = queryset.filter(operational_status=status_value)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = OperationalStatus.choices
        context["departments"] = visible_departments_queryset(self.request.user)
        context["filters"] = {
            "q": self.request.GET.get("q", ""),
            "department": self.request.GET.get("department", ""),
            "operational_status": self.request.GET.get("operational_status", ""),
            "archived": self.request.GET.get("archived", ""),
        }
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        context["can_manage_inventory"] = actor is not None and can_manage_inventory(actor)

        # Группировка отфильтрованных изделий по подразделению.
        # OrderedDict сохраняет порядок первого появления; финальная сортировка
        # по полному иерархическому имени даёт детерминированный порядок групп.
        devices = list(self.object_list)
        groups_map = OrderedDict()
        for device in devices:
            department = device.department
            if department.id not in groups_map:
                groups_map[department.id] = {
                    "department": department,
                    "devices": [],
                }
            groups_map[department.id]["devices"].append(device)

        grouped_devices = sorted(
            groups_map.values(),
            key=lambda g: (g["department"].full_name, g["department"].id),
        )
        context["grouped_devices"] = grouped_devices
        context["total_devices"] = len(devices)
        return context


class MedicalDeviceCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = MedicalDevice
    form_class = MedicalDeviceForm
    template_name = "inventory/device_form.html"
    success_url = reverse_lazy("inventory:list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def test_func(self):
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        return actor is not None and can_manage_inventory(actor)

    def form_valid(self, form):
        self.object = create_device_command(
            actor=self.request.user,
            payload=form.cleaned_data,
        )
        messages.success(self.request, "Изделие создано.")
        return redirect(self.get_success_url())


class MedicalDeviceDetailView(LoginRequiredMixin, DetailView):
    model = MedicalDevice
    template_name = "inventory/device_detail.html"
    context_object_name = "device"

    def get_queryset(self):
        return visible_devices_queryset(
            self.request.user,
            include_archived=True,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        context["can_manage_inventory"] = actor is not None and can_manage_inventory(actor)
        return context


class MedicalDeviceUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = MedicalDevice
    form_class = MedicalDeviceForm
    template_name = "inventory/device_form.html"
    success_url = reverse_lazy("inventory:list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_queryset(self):
        return visible_devices_queryset(
            self.request.user,
            include_archived=True,
        )

    def test_func(self):
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        return actor is not None and can_manage_inventory(actor)

    def form_valid(self, form):
        self.object = update_device_command(
            actor=self.request.user,
            device_id=self.get_object().pk,
            payload=form.cleaned_data,
        )
        messages.success(self.request, "Изделие обновлено.")
        return redirect(self.get_success_url())


class MedicalDeviceArchiveView(LoginRequiredMixin, UserPassesTestMixin, View):
    def test_func(self):
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        return actor is not None and can_manage_inventory(actor)

    def post(self, request, pk):
        try:
            archive_device_command(actor=request.user, device_id=pk)
        except PermissionDenied:
            return HttpResponseForbidden("Архивирование изделия запрещено")
        messages.success(request, "Изделие перемещено в архив.")
        return redirect("inventory:list")
