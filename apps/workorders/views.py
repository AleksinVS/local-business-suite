from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView

from apps.core.models import Department
from apps.inventory.models import MedicalDevice

from .forms import (
    KanbanColumnTitleForm,
    WorkOrderAttachmentForm,
    WorkOrderCommentForm,
    WorkOrderForm,
    WorkOrderRatingForm,
    WorkOrderUpdateForm,
)
from .models import KanbanColumnConfig, WorkOrder, WorkOrderAttachment, WorkOrderComment, WorkOrderStatus
from .policies import (
    can_comment,
    can_confirm_closure,
    can_create,
    can_edit,
    can_rate,
    can_transition,
    can_upload_attachment,
    is_customer,
    is_manager,
    is_technician,
)
from .services import confirm_closure, transition_workorder


def quick_transition_choices_for(user, workorder):
    return [
        (status, label)
        for status, label in WorkOrderStatus.choices
        if can_transition(user, workorder, status)
    ][:2]


def configured_columns():
    return list(KanbanColumnConfig.objects.order_by("position", "id"))


def column_card_context(column):
    return {
        "column_config": column,
        "rename_form": KanbanColumnTitleForm(instance=column),
    }


def visible_workorders_for(user):
    queryset = WorkOrder.objects.select_related("device", "author", "assignee", "department", "department__parent")
    if user.is_superuser or is_manager(user):
        return queryset
    if is_customer(user):
        return queryset
    if is_technician(user):
        return queryset.filter(Q(assignee=user) | Q(assignee__isnull=True) | Q(author=user))
    return queryset.none()


class WorkOrderBoardView(LoginRequiredMixin, TemplateView):
    template_name = "workorders/board.html"

    def get_queryset(self):
        queryset = visible_workorders_for(self.request.user).order_by("-updated_at")
        q = self.request.GET.get("q", "").strip()
        department = self.request.GET.get("department", "").strip()
        status_value = self.request.GET.get("status", "").strip()
        assignee = self.request.GET.get("assignee", "").strip()
        device = self.request.GET.get("device", "").strip()

        if q:
            queryset = queryset.filter(
                Q(number__icontains=q)
                | Q(title__icontains=q)
                | Q(description__icontains=q)
                | Q(device__name__icontains=q)
                | Q(device__model__icontains=q)
                | Q(device__serial_number__icontains=q)
            )
        if department:
            selected_department = Department.objects.filter(pk=department).first()
            if selected_department:
                queryset = queryset.filter(department_id__in=selected_department.descendant_ids())
            else:
                queryset = queryset.none()
        if status_value:
            queryset = queryset.filter(status=status_value)
        if assignee:
            queryset = queryset.filter(assignee__id=assignee)
        if device:
            queryset = queryset.filter(device__id=device)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset = self.get_queryset()
        column_configs = configured_columns()
        columns = OrderedDict((column.code, {"config": column, "items": []}) for column in column_configs)
        status_to_column = {}
        for column in column_configs:
            for status in column.statuses:
                status_to_column[status] = column.code
        display_number = 1
        for workorder in queryset:
            column_code = status_to_column.get(workorder.status)
            if not column_code:
                continue
            columns[column_code]["items"].append(
                {
                    "workorder": workorder,
                    "display_number": display_number,
                    "quick_transitions": quick_transition_choices_for(self.request.user, workorder),
                    "can_confirm_closure": can_confirm_closure(self.request.user, workorder),
                }
            )
            display_number += 1
        board_column_count = len(columns) if columns else 1
        context["board_columns"] = [
            {
                "key": code,
                "label": data["config"].title,
                "config": data["config"],
                "items": data["items"],
            }
            for code, data in columns.items()
        ]
        context["board_visible_slots"] = min(max(board_column_count, 1), 5)
        context["status_choices"] = WorkOrderStatus.choices
        context["departments"] = Department.objects.select_related("parent").order_by("parent_id", "name", "id")
        context["assignees"] = User.objects.order_by("first_name", "username")
        context["devices"] = MedicalDevice.objects.order_by("name")
        context["filters"] = {
            "q": self.request.GET.get("q", ""),
            "department": self.request.GET.get("department", ""),
            "status": self.request.GET.get("status", ""),
            "assignee": self.request.GET.get("assignee", ""),
            "device": self.request.GET.get("device", ""),
        }
        context["can_manage_board_columns"] = is_manager(self.request.user)
        return context

    def get_template_names(self):
        if self.request.htmx and self.request.htmx.target == "detail-panel":
            return ["workorders/partials/detail_panel_empty.html"]
        if self.request.htmx:
            return ["workorders/partials/board_columns.html"]
        return [self.template_name]


class WorkOrderCreateView(LoginRequiredMixin, CreateView):
    model = WorkOrder
    form_class = WorkOrderForm
    template_name = "workorders/workorder_form.html"

    def get_success_url(self):
        return reverse("workorders:detail", kwargs={"pk": self.object.pk})

    def dispatch(self, request, *args, **kwargs):
        if not can_create(request.user):
            return HttpResponseForbidden("Создание заявок запрещено")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.author = self.request.user
        if not is_manager(self.request.user):
            form.instance.assignee = None
        return super().form_valid(form)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if not is_manager(self.request.user):
            form.fields["assignee"].disabled = True
            form.fields["assignee"].required = False
        return form


class WorkOrderUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = WorkOrder
    form_class = WorkOrderUpdateForm
    template_name = "workorders/workorder_form.html"

    def test_func(self):
        return can_edit(self.request.user, self.get_object())

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, "Заявка обновлена.")
        return super().form_valid(form)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if not is_manager(self.request.user):
            form.fields["assignee"].disabled = True
            form.fields["assignee"].required = False
        return form

    def get_success_url(self):
        return reverse("workorders:detail", kwargs={"pk": self.object.pk})


class WorkOrderDetailView(LoginRequiredMixin, DetailView):
    model = WorkOrder
    template_name = "workorders/workorder_detail.html"
    context_object_name = "workorder"

    def get_queryset(self):
        return visible_workorders_for(self.request.user).prefetch_related(
            "comments__author", "attachments", "transitions__actor"
        )

    def get_template_names(self):
        if self.request.htmx:
            return ["workorders/partials/detail_panel.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["comment_form"] = WorkOrderCommentForm()
        context["attachment_form"] = WorkOrderAttachmentForm()
        context["rating_form"] = WorkOrderRatingForm(instance=self.object)
        context["transition_choices"] = [
            (status, label)
            for status, label in WorkOrderStatus.choices
            if can_transition(self.request.user, self.object, status)
        ]
        context["can_edit"] = can_edit(self.request.user, self.object)
        context["can_confirm_closure"] = can_confirm_closure(self.request.user, self.object)
        context["can_rate"] = can_rate(self.request.user, self.object)
        context["can_upload_attachment"] = can_upload_attachment(self.request.user, self.object)
        context["can_comment"] = can_comment(self.request.user, self.object)
        return context


class WorkOrderCommentCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        workorder = get_object_or_404(visible_workorders_for(request.user), pk=pk)
        if not can_comment(request.user, workorder):
            return HttpResponseForbidden("Комментарии недоступны")
        form = WorkOrderCommentForm(request.POST)
        if form.is_valid():
            WorkOrderComment.objects.create(
                workorder=workorder,
                author=request.user,
                body=form.cleaned_data["body"],
            )
            if request.htmx:
                return render(
                    request,
                    "workorders/partials/comments.html",
                    {
                        "workorder": workorder,
                        "comment_form": WorkOrderCommentForm(),
                    },
                )
            messages.success(request, "Комментарий добавлен.")
            return redirect("workorders:detail", pk=workorder.pk)
        if request.htmx:
            return render(
                request,
                "workorders/partials/comments.html",
                {"workorder": workorder, "comment_form": form},
                status=400,
            )
        messages.error(request, "Не удалось добавить комментарий.")
        return redirect("workorders:detail", pk=workorder.pk)


class WorkOrderAttachmentCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        workorder = get_object_or_404(visible_workorders_for(request.user), pk=pk)
        if not can_upload_attachment(request.user, workorder):
            return HttpResponseForbidden("Загрузка файлов запрещена")
        form = WorkOrderAttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]
            WorkOrderAttachment.objects.create(
                workorder=workorder,
                uploaded_by=request.user,
                file=uploaded_file,
                content_type=getattr(uploaded_file, "content_type", ""),
            )
            if request.htmx:
                return render(
                    request,
                    "workorders/partials/attachments.html",
                    {
                        "workorder": workorder,
                        "attachment_form": WorkOrderAttachmentForm(),
                    },
                )
            messages.success(request, "Файл добавлен.")
            return redirect("workorders:detail", pk=workorder.pk)
        if request.htmx:
            return render(
                request,
                "workorders/partials/attachments.html",
                {"workorder": workorder, "attachment_form": form},
                status=400,
            )
        messages.error(request, "Не удалось загрузить файл.")
        return redirect("workorders:detail", pk=workorder.pk)


class WorkOrderTransitionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        workorder = get_object_or_404(visible_workorders_for(request.user), pk=pk)
        target_status = request.POST.get("status", "")
        if not can_transition(request.user, workorder, target_status):
            return HttpResponseForbidden("Переход запрещен")
        transition_workorder(workorder=workorder, user=request.user, to_status=target_status)
        workorder.refresh_from_db()
        transition_choices = [
            (status, label)
            for status, label in WorkOrderStatus.choices
            if can_transition(request.user, workorder, status)
        ]
        if request.htmx:
            if request.htmx.target == "board-columns":
                board_view = WorkOrderBoardView()
                board_view.request = request
                board_view.args = ()
                board_view.kwargs = {}
                return render(
                    request,
                    "workorders/partials/board_columns.html",
                    board_view.get_context_data(),
                )
            return render(
                request,
                "workorders/partials/status_section.html",
                {
                    "workorder": workorder,
                    "transition_choices": transition_choices,
                    "can_confirm_closure": can_confirm_closure(request.user, workorder),
                },
            )
        messages.success(request, "Статус заявки обновлен.")
        return redirect("workorders:detail", pk=workorder.pk)


class WorkOrderConfirmClosureView(LoginRequiredMixin, View):
    def post(self, request, pk):
        workorder = get_object_or_404(visible_workorders_for(request.user), pk=pk)
        if not can_confirm_closure(request.user, workorder):
            return HttpResponseForbidden("Подтверждение закрытия запрещено")
        confirm_closure(workorder=workorder, user=request.user)
        workorder.refresh_from_db()
        transition_choices = [
            (status, label)
            for status, label in WorkOrderStatus.choices
            if can_transition(request.user, workorder, status)
        ]
        context = {
            "workorder": workorder,
            "transition_choices": transition_choices,
            "can_confirm_closure": can_confirm_closure(request.user, workorder),
        }
        if request.htmx:
            return render(request, "workorders/partials/status_section.html", context)
        messages.success(request, "Закрытие заявки подтверждено.")
        return redirect("workorders:detail", pk=workorder.pk)


class WorkOrderRateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        workorder = get_object_or_404(visible_workorders_for(request.user), pk=pk)
        if not can_rate(request.user, workorder):
            return HttpResponseForbidden("Оценка запрещена")
        form = WorkOrderRatingForm(request.POST, instance=workorder)
        if form.is_valid():
            form.save()
            workorder.refresh_from_db()
            context = {
                "workorder": workorder,
                "rating_form": WorkOrderRatingForm(instance=workorder),
                "can_rate": can_rate(request.user, workorder),
            }
            if request.htmx:
                return render(request, "workorders/partials/rating_section.html", context)
            messages.success(request, "Оценка сохранена.")
            return redirect("workorders:detail", pk=workorder.pk)
        if request.htmx:
            return render(
                request,
                "workorders/partials/rating_section.html",
                {
                    "workorder": workorder,
                    "rating_form": form,
                    "can_rate": can_rate(request.user, workorder),
                },
                status=400,
            )
        messages.error(request, "Не удалось сохранить оценку.")
        return redirect("workorders:detail", pk=workorder.pk)


class KanbanColumnRenameView(LoginRequiredMixin, View):
    def post(self, request, pk):
        if not is_manager(request.user):
            return HttpResponseForbidden("Изменение колонок запрещено")
        column = get_object_or_404(KanbanColumnConfig, pk=pk)
        form = KanbanColumnTitleForm(request.POST, instance=column)
        if form.is_valid():
            form.save()
        board_view = WorkOrderBoardView()
        board_view.request = request
        board_view.args = ()
        board_view.kwargs = {}
        if request.htmx and request.htmx.target == f"column-config-{column.pk}":
            return render(
                request,
                "workorders/partials/column_config_card.html",
                column_card_context(column),
                status=200 if form.is_valid() else 400,
            )
        return render(
            request,
            "workorders/partials/board_columns.html",
            board_view.get_context_data(),
            status=200 if form.is_valid() else 400,
        )


class KanbanColumnEditView(LoginRequiredMixin, View):
    def get(self, request, pk):
        if not is_manager(request.user):
            return HttpResponseForbidden("Изменение колонок запрещено")
        column = get_object_or_404(KanbanColumnConfig, pk=pk)
        return render(
            request,
            "workorders/partials/column_config_form.html",
            column_card_context(column),
        )


class KanbanColumnDisplayView(LoginRequiredMixin, View):
    def get(self, request, pk):
        if not is_manager(request.user):
            return HttpResponseForbidden("Изменение колонок запрещено")
        column = get_object_or_404(KanbanColumnConfig, pk=pk)
        return render(
            request,
            "workorders/partials/column_config_card.html",
            column_card_context(column),
        )
