from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import WaitingListEntryForm, WaitingListStatusForm
from .models import WaitingListEntry, WaitingListStatus
from .services import (
    WaitingListValidationError,
    create_entry,
    transition_entry,
    update_entry,
)


class WaitingListAccessMixin(LoginRequiredMixin):
    """Mixin ensuring only authenticated users access waiting list."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseForbidden("Доступ только для авторизованных пользователей.")
        return super().dispatch(request, *args, **kwargs)


class WaitingListDashboardView(WaitingListAccessMixin, ListView):
    """Main waiting list dashboard with filtering and sorting."""

    model = WaitingListEntry
    template_name = "waiting_list/dashboard.html"
    context_object_name = "entries"

    def get_queryset(self):
        queryset = WaitingListEntry.objects.all().order_by("-created_at")

        # Filters from querystring
        service = self.request.GET.get("service", "").strip()
        search = self.request.GET.get("search", "").strip()
        date_from = self.request.GET.get("date_from", "").strip()
        cito_only = self.request.GET.get("cito") == "1"

        if service and service != "all":
            queryset = queryset.filter(service_id=service)
        if search:
            queryset = queryset.filter(
                Q(patient_name__icontains=search)
                | Q(patient_dob__icontains=search)
            )
        if date_from:
            queryset = queryset.filter(date_tag__gte=date_from)
        if cito_only:
            queryset = queryset.filter(priority_cito=True)

        # Sorting
        sort = self.request.GET.get("sort", "created_at")
        order = self.request.GET.get("order", "desc")
        if order == "asc":
            sort = sort
        else:
            sort = f"-{sort}"
        queryset = queryset.order_by(sort)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["service_choices"] = WaitingListEntry._meta.get_field("service_id").choices
        context["status_choices"] = WaitingListStatus.choices
        context["filters"] = {
            "service": self.request.GET.get("service", "all"),
            "search": self.request.GET.get("search", ""),
            "date_from": self.request.GET.get("date_from", ""),
            "cito": self.request.GET.get("cito") == "1",
        }
        return context

    def get_template_names(self):
        if self.request.htmx and self.request.htmx.target == "entry-table":
            return ["waiting_list/partials/entry_table.html"]
        return [self.template_name]


class WaitingListEntryCreateView(WaitingListAccessMixin, CreateView):
    """Create a new waiting list entry."""

    model = WaitingListEntry
    form_class = WaitingListEntryForm
    template_name = "waiting_list/entry_form.html"

    def get_template_names(self):
        if self.request.htmx:
            return ["waiting_list/partials/entry_form_partial.html"]
        return [self.template_name]

    def get_success_url(self):
        return reverse("waiting_list:dashboard")

    def form_valid(self, form):
        try:
            entry = create_entry(
                author=self.request.user,
                patient_name=form.cleaned_data["patient_name"],
                patient_dob=form.cleaned_data["patient_dob"],
                patient_phone=form.cleaned_data["patient_phone"],
                service_id=form.cleaned_data["service_id"],
                date_tag=form.cleaned_data.get("date_tag"),
                date_end=form.cleaned_data.get("date_end"),
                priority_cito=form.cleaned_data.get("priority_cito", False),
                comment=form.cleaned_data.get("comment", ""),
            )
            response = redirect("waiting_list:dashboard")
            if self.request.htmx:
                response["HX-Redirect"] = self.get_success_url()
            else:
                messages.success(self.request, "Запись добавлена в лист ожидания.")
            return response
        except WaitingListValidationError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)


class WaitingListEntryDetailView(WaitingListAccessMixin, DetailView):
    """Detail view for a waiting list entry with audit timeline."""

    model = WaitingListEntry
    template_name = "waiting_list/entry_detail.html"
    context_object_name = "entry"

    def get_queryset(self):
        return WaitingListEntry.objects.prefetch_related("audit_logs__actor")

    def get_template_names(self):
        if self.request.htmx:
            return ["waiting_list/partials/entry_detail_panel.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_form"] = WaitingListStatusForm(instance=self.object)
        context["status_choices"] = WaitingListStatus.choices
        context["transition_choices_vals"] = WaitingListStatus.values  # Simplified for now
        return context


class WaitingListEntryUpdateView(WaitingListAccessMixin, UpdateView):
    """Update an existing waiting list entry."""

    model = WaitingListEntry
    form_class = WaitingListEntryForm
    template_name = "waiting_list/entry_form.html"
    context_object_name = "entry"

    def get_queryset(self):
        return WaitingListEntry.objects.all()

    def get_template_names(self):
        if self.request.htmx:
            return ["waiting_list/partials/entry_form_partial.html"]
        return [self.template_name]

    def get_success_url(self):
        if self.request.htmx:
            return reverse("waiting_list:detail", kwargs={"pk": self.object.pk})
        return reverse("waiting_list:detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        try:
            entry = update_entry(
                entry=self.object,
                user=self.request.user,
                patient_name=form.cleaned_data["patient_name"],
                patient_dob=form.cleaned_data["patient_dob"],
                patient_phone=form.cleaned_data["patient_phone"],
                service_id=form.cleaned_data["service_id"],
                date_tag=form.cleaned_data.get("date_tag"),
                date_end=form.cleaned_data.get("date_end"),
                priority_cito=form.cleaned_data.get("priority_cito", False),
                comment=form.cleaned_data.get("comment", ""),
            )
            if self.request.htmx:
                # After successful update in htmx, return the detail view of that entry
                detail_view = WaitingListEntryDetailView()
                detail_view.request = self.request
                detail_view.args = self.args
                detail_view.kwargs = self.kwargs
                detail_view.object = entry
                return render(
                    self.request,
                    "waiting_list/partials/entry_detail_panel.html",
                    detail_view.get_context_data(object=entry),
                )
            messages.success(self.request, "Запись обновлена.")
            return redirect("waiting_list:detail", pk=self.object.pk)
        except WaitingListValidationError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)


class WaitingListTransitionView(WaitingListAccessMixin, View):
    """Quick status transition for HTMX-driven dashboard."""

    def post(self, request, pk):
        entry = get_object_or_404(WaitingListEntry, pk=pk)
        target_status = request.POST.get("status", "")

        if target_status not in WaitingListStatus.values:
            return HttpResponseForbidden("Недопустимый статус.")

        try:
            transition_entry(entry=entry, user=request.user, to_status=target_status)
            entry.refresh_from_db()

            if request.htmx:
                return render(
                    request,
                    "waiting_list/partials/entry_detail_panel.html",
                    {
                        "entry": entry,
                        "status_form": WaitingListStatusForm(instance=entry),
                        "status_choices": WaitingListStatus.choices,
                        "transition_choices_vals": WaitingListStatus.values,
                    },
                )
            messages.success(request, "Статус обновлен.")
            return redirect("waiting_list:dashboard")
        except Exception as e:
            if request.htmx:
                return render(
                    request,
                    "waiting_list/partials/entry_detail_panel.html",
                    {
                        "entry": entry,
                        "status_form": WaitingListStatusForm(instance=entry),
                        "transition_choices": WaitingListStatus.choices,
                        "error": str(e),
                    },
                    status=400,
                )
            messages.error(request, f"Ошибка: {e}")
            return redirect("waiting_list:detail", pk=entry.pk)
