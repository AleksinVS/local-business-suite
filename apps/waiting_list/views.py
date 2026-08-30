import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.core.contract_store import get_contract
from apps.core.status_colors import status_color_css_variables

from .forms import WaitingListEntryForm, WaitingListStatusForm
from .models import WaitingListEntry, WaitingListStatus
from .policies import (
    allowed_waiting_list_transition_targets,
    can_create_waiting_list,
    can_edit_waiting_list_entry,
    can_transition_waiting_list_entry,
    can_view_waiting_list,
)
from .selectors import visible_waiting_list_entries
from .services import (
    WaitingListValidationError,
    create_entry,
    transition_entry,
    update_entry,
)


def page_context_json(payload):
    return json.dumps(payload, ensure_ascii=False)


def _role_rules_snapshot(request):
    snapshot = getattr(request, "_waiting_role_rules", None)
    if snapshot is None:
        snapshot = get_contract("role_rules", request=request)
        request._waiting_role_rules = snapshot
    return snapshot


def _waiting_list_status_color_style(request):
    return status_color_css_variables(
        get_contract("waiting_list_status_colors", request=request),
        prefix="waiting-list-status",
    )


def waiting_list_detail_page_context(request, entry):
    return {
        "schema_version": "1",
        "page": {
            "path": request.path,
            "title": "Запись листа ожидания",
            "module": "waiting_list",
            "view": "detail",
        },
        "selection": {
            "object_type": "waiting_list_entry",
            "object_id": str(entry.pk),
            "source_code": "waiting_list",
            "display": f"{entry.pk}. {entry.get_service_id_display()}",
        },
        "filters": {},
        "ui_state": {"right_drawer": "open", "focused_region": "detail_panel"},
    }


def waiting_list_detail_context(request, entry, *, form=None, error=None):
    """Build one context contract for full-page and HTMX detail rendering."""
    if form is None:
        form = WaitingListEntryForm(instance=entry)
    rules_payload = _role_rules_snapshot(request)
    allowed_targets = allowed_waiting_list_transition_targets(
        request.user, entry, rules_payload=rules_payload
    )
    status_form = WaitingListStatusForm(instance=entry)
    status_form.fields["status"].choices = [
        (status, label)
        for status, label in WaitingListStatus.choices
        if status in allowed_targets
    ]
    return {
        "entry": entry,
        "form": form,
        "status_form": status_form,
        "status_choices": [
            (status, label)
            for status, label in WaitingListStatus.choices
            if status in allowed_targets
        ],
        "can_edit": can_edit_waiting_list_entry(
            request.user, entry, rules_payload=rules_payload
        ),
        "can_transition": can_transition_waiting_list_entry(
            request.user, entry, rules_payload=rules_payload
        ),
        "detail_ai_context_json": page_context_json(
            waiting_list_detail_page_context(request, entry)
        ),
        "waiting_list_status_color_style": _waiting_list_status_color_style(request),
        "is_standalone_detail": not request.htmx,
        "error": error,
    }


class WaitingListAccessMixin(LoginRequiredMixin):
    """Mixin ensuring only users with the view_waiting_list capability get access."""

    def dispatch(self, request, *args, **kwargs):
        rules_payload = _role_rules_snapshot(request)
        if request.user.is_authenticated and not can_view_waiting_list(
            request.user, rules_payload=rules_payload
        ):
            return HttpResponseForbidden(
                "Доступ к листу ожидания есть только у ролей с правом просмотра (по умолчанию — «Врач»)."
            )
        return super().dispatch(request, *args, **kwargs)


class WaitingListDashboardView(WaitingListAccessMixin, ListView):
    """Main waiting list dashboard with filtering and sorting."""

    model = WaitingListEntry
    template_name = "waiting_list/dashboard.html"
    context_object_name = "entries"

    def get_queryset(self):
        queryset = visible_waiting_list_entries(
            self.request.user,
            rules_payload=_role_rules_snapshot(self.request),
        ).order_by("-created_at")

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
            sort_field = sort
        else:
            sort_field = f"-{sort}"
        queryset = queryset.order_by(sort_field, "-created_at")

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["service_choices"] = WaitingListEntry._meta.get_field("service_id").choices
        context["status_choices"] = WaitingListStatus.choices
        context["waiting_list_status_color_style"] = _waiting_list_status_color_style(
            self.request
        )
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

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not can_create_waiting_list(
            request.user, rules_payload=_role_rules_snapshot(request)
        ):
            return HttpResponseForbidden("Создание записей запрещено.")
        return super().dispatch(request, *args, **kwargs)

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
            if self.request.htmx:
                response = HttpResponse(status=204)
                response["HX-Trigger"] = "waitingListEntryCreated"
                return response
            messages.success(self.request, "Запись добавлена в лист ожидания.")
            return redirect("waiting_list:dashboard")
        except WaitingListValidationError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)


class WaitingListEntryDetailView(WaitingListAccessMixin, DetailView):
    """Detail view for a waiting list entry with audit timeline."""

    model = WaitingListEntry
    template_name = "waiting_list/entry_detail.html"
    context_object_name = "entry"

    def get_queryset(self):
        return visible_waiting_list_entries(
            self.request.user,
            rules_payload=_role_rules_snapshot(self.request),
            queryset=WaitingListEntry.objects.prefetch_related("audit_logs__actor"),
        )

    def get_template_names(self):
        if self.request.htmx:
            return ["waiting_list/partials/entry_detail_panel.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(waiting_list_detail_context(self.request, self.object))
        return context


class WaitingListEntryUpdateView(WaitingListAccessMixin, UpdateView):
    """Validate inline edits and return the same detail surface."""

    model = WaitingListEntry
    form_class = WaitingListEntryForm
    template_name = "waiting_list/entry_detail.html"
    context_object_name = "entry"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        entry = self.get_object()
        if not can_edit_waiting_list_entry(
            request.user, entry, rules_payload=_role_rules_snapshot(request)
        ):
            return HttpResponseForbidden("Редактирование этой записи запрещено.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return visible_waiting_list_entries(
            self.request.user,
            rules_payload=_role_rules_snapshot(self.request),
        )

    def get_template_names(self):
        if self.request.htmx:
            return ["waiting_list/partials/entry_detail_panel.html"]
        return [self.template_name]

    def get_success_url(self):
        return reverse("waiting_list:detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            waiting_list_detail_context(
                self.request,
                self.object,
                form=context["form"],
            )
        )
        return context

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
                response = render(
                    self.request,
                    "waiting_list/partials/entry_detail_panel.html",
                    waiting_list_detail_context(self.request, entry),
                )
                response["HX-Trigger"] = "waitingListEntryUpdated"
                return response
            messages.success(self.request, "Запись обновлена.")
            return redirect("waiting_list:detail", pk=self.object.pk)
        except WaitingListValidationError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)


class WaitingListTransitionView(WaitingListAccessMixin, View):
    """Quick status transition for HTMX-driven dashboard."""

    def post(self, request, pk):
        target_status = request.POST.get("status", "")

        if target_status not in WaitingListStatus.values:
            return HttpResponseForbidden("Недопустимый статус.")

        rules_payload = _role_rules_snapshot(request)
        entry = get_object_or_404(
            visible_waiting_list_entries(request.user, rules_payload=rules_payload),
            pk=pk,
        )
        if not can_transition_waiting_list_entry(
            request.user, entry, target_status, rules_payload=rules_payload
        ):
            return HttpResponseForbidden("Смена статуса этой записи запрещена.")

        try:
            transition_entry(entry=entry, user=request.user, to_status=target_status)
            entry.refresh_from_db()

            if request.htmx:
                return render(
                    request,
                    "waiting_list/partials/entry_detail_panel.html",
                    waiting_list_detail_context(request, entry),
                )
            messages.success(request, "Статус обновлен.")
            return redirect("waiting_list:dashboard")
        except WaitingListValidationError as e:
            if request.htmx:
                return render(
                    request,
                    "waiting_list/partials/entry_detail_panel.html",
                    waiting_list_detail_context(request, entry, error=str(e)),
                    status=400,
                )
            messages.error(request, f"Ошибка: {e}")
            return redirect("waiting_list:detail", pk=entry.pk)
