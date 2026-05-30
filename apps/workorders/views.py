from collections import OrderedDict
import json
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth import get_user_model
from django.db.models import Q, Count

User = get_user_model()
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView

from apps.core.models import Department

from .forms import (
    KanbanColumnTitleForm,
    WorkOrderAttachmentForm,
    WorkOrderCommentForm,
    WorkOrderForm,
    WorkOrderRatingForm,
    WorkOrderUpdateForm,
)
from .models import (
    Board,
    KanbanColumnConfig,
    WorkOrder,
    WorkOrderAttachment,
    WorkOrderComment,
    WorkOrderStatus,
)
from .policies import (
    can_comment,
    can_confirm_closure,
    can_create,
    can_edit,
    can_manage_assignments,
    can_manage_board_columns,
    can_rate,
    can_transition,
    can_upload_attachment,
)
from .selectors import (
    visible_boards_queryset,
    visible_departments_queryset,
    visible_devices_queryset,
    visible_workorders_queryset,
)
from .services import confirm_closure, transition_workorder
from .tree import build_workorder_tree


VIEW_BOARD = "board"
VIEW_TREE = "tree"
VIEW_MODES = {VIEW_BOARD, VIEW_TREE}


def quick_transition_choices_for(user, workorder):
    return [
        (status, label)
        for status, label in WorkOrderStatus.choices
        if can_transition(user, workorder, status)
    ]


def _stepper_context(user, workorder):
    transitions = quick_transition_choices_for(user, workorder)
    return {
        "workorder": workorder,
        "transition_choices": transitions,
        "transition_choices_vals": {s for s, _ in transitions},
        "status_choices": WorkOrderStatus.choices,
        "can_confirm_closure": can_confirm_closure(user, workorder),
    }


def configured_columns(board=None):
    qs = KanbanColumnConfig.objects.order_by("position", "id")
    if board is not None:
        qs = qs.filter(board=board)
    return list(qs)


def drop_status_for_column(user, workorder, column):
    if workorder.status in column.statuses:
        return None
    for status in column.statuses:
        if can_transition(user, workorder, status):
            return status
    return None


def column_card_context(column):
    return {
        "column_config": column,
        "rename_form": KanbanColumnTitleForm(instance=column),
    }


def page_context_json(payload):
    return json.dumps(payload, ensure_ascii=False)


def _requested_view_mode(request):
    view_mode = request.GET.get("view", VIEW_BOARD).strip()
    if view_mode not in VIEW_MODES:
        return VIEW_BOARD
    return view_mode


def _with_query(url, params):
    cleaned = {key: value for key, value in params.items() if value not in {None, ""}}
    if not cleaned:
        return url
    return f"{url}?{urlencode(cleaned)}"


def _mark_workorders_changed(response):
    response["HX-Trigger"] = "workordersChanged"
    return response


def _related_user_search_q(relation_name, query):
    fields = ("username", "first_name", "last_name", "email")
    search_query = Q()
    for field in fields:
        search_query |= Q(**{f"{relation_name}__{field}__icontains": query})

    tokens = [token.strip() for token in query.split() if token.strip()]
    if len(tokens) > 1:
        token_query = Q()
        for token in tokens:
            per_token_query = Q()
            for field in fields:
                per_token_query |= Q(
                    **{f"{relation_name}__{field}__icontains": token}
                )
            token_query &= per_token_query
        search_query |= token_query
    return search_query


def _department_search_ids(query):
    matched_ids = set(
        Department.objects.filter(name__icontains=query).values_list("id", flat=True)
    )
    if not matched_ids:
        return set()

    children_map = {}
    for department_id, parent_id in Department.objects.values_list("id", "parent_id"):
        children_map.setdefault(parent_id, []).append(department_id)

    department_ids = set()
    stack = list(matched_ids)
    while stack:
        department_id = stack.pop()
        if department_id in department_ids:
            continue
        department_ids.add(department_id)
        stack.extend(children_map.get(department_id, []))
    return department_ids


def workorders_board_page_context(request, board, view_mode=VIEW_BOARD):
    return {
        "schema_version": "1",
        "page": {
            "path": request.path,
            "title": "Дерево заявок" if view_mode == VIEW_TREE else "Канбан заявок",
            "module": "workorders",
            "view": view_mode,
        },
        "selection": {},
        "filters": {
            "board": board.slug if board else "",
            "q": request.GET.get("q", ""),
            "department": request.GET.get("department", ""),
            "status": request.GET.get("status", ""),
            "assignee": request.GET.get("assignee", ""),
            "device": request.GET.get("device", ""),
        },
        "ui_state": {"focused_region": "tree" if view_mode == VIEW_TREE else "board"},
    }


def workorder_detail_page_context(request, workorder):
    return {
        "schema_version": "1",
        "page": {
            "path": request.path,
            "title": "Карточка заявки",
            "module": "workorders",
            "view": "detail",
        },
        "selection": {
            "object_type": "workorder",
            "object_id": str(workorder.pk),
            "source_code": "workorders",
            "display": f"{workorder.number}. {workorder.title}",
        },
        "filters": {},
        "ui_state": {"right_drawer": "open", "focused_region": "detail_panel"},
    }


class WorkOrderBoardView(LoginRequiredMixin, TemplateView):
    template_name = "workorders/board.html"

    def get_view_mode(self):
        return _requested_view_mode(self.request)

    def get_board(self):
        slug = self.kwargs.get("board_slug")
        boards = visible_boards_queryset(self.request.user)
        if slug:
            return get_object_or_404(boards, slug=slug)
        board = boards.first()
        return board

    def get_queryset(self, board):
        queryset = visible_workorders_queryset(self.request.user, board=board).order_by(
            "-updated_at"
        )
        queryset = queryset.annotate(
            comment_count=Count("comments", distinct=True),
            attachment_count=Count("attachments", distinct=True),
        )
        q = self.request.GET.get("q", "").strip()
        department = self.request.GET.get("department", "").strip()
        status_value = self.request.GET.get("status", "").strip()
        assignee = self.request.GET.get("assignee", "").strip()
        device = self.request.GET.get("device", "").strip()

        if q:
            matched_department_ids = _department_search_ids(q)
            search_filter = (
                Q(number__icontains=q)
                | Q(title__icontains=q)
                | Q(description__icontains=q)
                | Q(device__name__icontains=q)
                | Q(device__model__icontains=q)
                | Q(device__serial_number__icontains=q)
                | _related_user_search_q("author", q)
                | _related_user_search_q("assignee", q)
            )
            if matched_department_ids:
                search_filter |= Q(department_id__in=matched_department_ids)
            queryset = queryset.filter(search_filter)
        if department:
            selected_department = Department.objects.filter(pk=department).first()
            if selected_department:
                queryset = queryset.filter(
                    department_id__in=selected_department.descendant_ids()
                )
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
        board = self.get_board()
        view_mode = self.get_view_mode()
        context["page_ai_context_json"] = page_context_json(
            workorders_board_page_context(self.request, board, view_mode=view_mode)
        )
        if not board:
            context["no_boards"] = True
            context["current_view"] = view_mode
            return context

        queryset = self.get_queryset(board)
        column_configs = list(board.columns.order_by("position", "id"))
        columns = OrderedDict(
            (column.code, {"config": column, "items": []}) for column in column_configs
        )
        status_to_column = {}
        for column in column_configs:
            for status in column.statuses:
                status_to_column[status] = column.code
        for workorder in queryset:
            column_code = status_to_column.get(workorder.status)
            if not column_code:
                continue
            drop_targets = {
                column.code: status
                for column in column_configs
                for status in [
                    drop_status_for_column(self.request.user, workorder, column)
                ]
                if status
            }
            columns[column_code]["items"].append(
                {
                    "workorder": workorder,
                    "quick_transitions": quick_transition_choices_for(
                        self.request.user, workorder
                    ),
                    "can_confirm_closure": can_confirm_closure(
                        self.request.user, workorder
                    ),
                    "can_drag": bool(drop_targets),
                }
            )
        board_column_count = len(columns) if columns else 1
        query_for_board = self.request.GET.copy()
        query_for_board["view"] = VIEW_BOARD
        query_for_tree = self.request.GET.copy()
        query_for_tree["view"] = VIEW_TREE
        context["current_board"] = board
        context["current_view"] = view_mode
        context["view_urls"] = {
            VIEW_BOARD: f"{self.request.path}?{query_for_board.urlencode()}",
            VIEW_TREE: f"{self.request.path}?{query_for_tree.urlencode()}",
        }
        context["visible_boards"] = visible_boards_queryset(self.request.user)
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
        if view_mode == VIEW_TREE:
            context["workorder_tree"] = build_workorder_tree(
                queryset,
                can_create_workorder=can_create(self.request.user),
            )
        context["status_choices"] = WorkOrderStatus.choices
        context["departments"] = visible_departments_queryset(self.request.user)
        context["assignees"] = User.objects.order_by("first_name", "username")
        context["devices"] = visible_devices_queryset(self.request.user)
        context["filters"] = {
            "view": view_mode,
            "q": self.request.GET.get("q", ""),
            "department": self.request.GET.get("department", ""),
            "status": self.request.GET.get("status", ""),
            "assignee": self.request.GET.get("assignee", ""),
            "device": self.request.GET.get("device", ""),
        }
        context["can_manage_board_columns"] = can_manage_board_columns(
            self.request.user
        )
        return context

    def get_template_names(self):
        if self.request.htmx and self.request.htmx.target == "detail-panel":
            return ["workorders/partials/detail_panel_empty.html"]
        if self.request.htmx and self.request.htmx.target == "board-columns":
            return ["workorders/partials/board_columns.html"]
        if self.request.htmx and self.request.htmx.target == "workorders-tree":
            return ["workorders/partials/tree_view.html"]
        if self.request.htmx and self.request.htmx.target == "workorders-view":
            return ["workorders/partials/workorders_view.html"]
        if self.request.htmx:
            return ["workorders/partials/workorders_view.html"]
        return [self.template_name]


class WorkOrderCreateView(LoginRequiredMixin, CreateView):
    model = WorkOrder
    form_class = WorkOrderForm
    template_name = "workorders/workorder_form.html"

    def get_initial(self):
        initial = super().get_initial()
        board_id = self.request.GET.get("board")
        if board_id:
            initial["board"] = board_id
        department_id = self.request.GET.get("department")
        if department_id and visible_departments_queryset(self.request.user).filter(
            pk=department_id
        ).exists():
            initial["department"] = department_id
        device_id = self.request.GET.get("device")
        if device_id:
            device = (
                visible_devices_queryset(self.request.user)
                .filter(pk=device_id)
                .first()
            )
            if device:
                initial["device"] = device.pk
                initial.setdefault("department", device.department_id)
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_template_names(self):
        if self.request.htmx:
            return ["workorders/partials/workorder_form_partial.html"]
        return [self.template_name]

    def get_success_url(self):
        if self.request.htmx:
            if self.object and self.object.board_id:
                url = reverse(
                    "workorders:board_specific",
                    kwargs={"board_slug": self.object.board.slug},
                )
            else:
                url = reverse("workorders:board")
            return_view = self.request.POST.get("return_view") or self.request.GET.get(
                "return_view"
            )
            return _with_query(
                url,
                {"view": return_view if return_view in VIEW_MODES else ""},
            )
        return reverse("workorders:detail", kwargs={"pk": self.object.pk})

    def dispatch(self, request, *args, **kwargs):
        if not can_create(request.user):
            return HttpResponseForbidden("Создание заявок запрещено")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.author = self.request.user
        if not can_manage_assignments(self.request.user):
            form.instance.assignee = None
        if self.request.htmx:
            self.object = form.save()
            response = HttpResponse(status=204)
            response["HX-Redirect"] = self.get_success_url()
            return response
        response = super().form_valid(form)
        return response

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if not can_manage_assignments(self.request.user):
            form.fields["assignee"].disabled = True
            form.fields["assignee"].required = False
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return_view = self.request.GET.get("return_view") or self.request.GET.get("view")
        context["return_view"] = return_view if return_view in VIEW_MODES else VIEW_BOARD
        return context


class WorkOrderUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = WorkOrder
    form_class = WorkOrderUpdateForm
    template_name = "workorders/workorder_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_template_names(self):
        if self.request.htmx:
            return ["workorders/partials/workorder_edit_form_partial.html"]
        return [self.template_name]

    def test_func(self):
        return can_edit(self.request.user, self.get_object())

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, "Заявка обновлена.")
        if self.request.htmx:
            # Re-render the detail panel for this workorder
            detail_view = WorkOrderDetailView()
            detail_view.request = self.request
            detail_view.args = self.args
            detail_view.kwargs = self.kwargs
            detail_view.object = self.object
            response = render(
                self.request,
                "workorders/partials/detail_panel.html",
                detail_view.get_context_data(object=self.object),
            )
            return _mark_workorders_changed(response)
        return super().form_valid(form)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if not can_manage_assignments(self.request.user):
            form.fields["assignee"].disabled = True
            form.fields["assignee"].required = False
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["workorder"] = self.get_object()
        return context

    def get_success_url(self):
        return reverse("workorders:detail", kwargs={"pk": self.object.pk})


class WorkOrderDetailView(LoginRequiredMixin, DetailView):
    model = WorkOrder
    template_name = "workorders/workorder_detail.html"
    context_object_name = "workorder"

    def get_queryset(self):
        return visible_workorders_queryset(self.request.user).prefetch_related(
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
        context.update(_stepper_context(self.request.user, self.object))
        context["can_edit"] = can_edit(self.request.user, self.object)
        context["can_confirm_closure"] = can_confirm_closure(
            self.request.user, self.object
        )
        context["can_rate"] = can_rate(self.request.user, self.object)
        context["can_upload_attachment"] = can_upload_attachment(
            self.request.user, self.object
        )
        context["can_comment"] = can_comment(self.request.user, self.object)
        context["detail_ai_context_json"] = page_context_json(
            workorder_detail_page_context(self.request, self.object)
        )
        return context


class WorkOrderCommentCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        workorder = get_object_or_404(visible_workorders_queryset(request.user), pk=pk)
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
                response = render(
                    request,
                    "workorders/partials/comments.html",
                    {
                        "workorder": workorder,
                        "comment_form": WorkOrderCommentForm(),
                    },
                )
                return _mark_workorders_changed(response)
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
        workorder = get_object_or_404(visible_workorders_queryset(request.user), pk=pk)
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
                response = render(
                    request,
                    "workorders/partials/attachments.html",
                    {
                        "workorder": workorder,
                        "attachment_form": WorkOrderAttachmentForm(),
                        "can_upload_attachment": True,
                    },
                )
                return _mark_workorders_changed(response)
            messages.success(request, "Файл добавлен.")
            return redirect("workorders:detail", pk=workorder.pk)
        if request.htmx:
            return render(
                request,
                "workorders/partials/attachments.html",
                {
                    "workorder": workorder,
                    "attachment_form": form,
                    "can_upload_attachment": True,
                },
                status=400,
            )
        messages.error(request, "Не удалось загрузить файл.")
        return redirect("workorders:detail", pk=workorder.pk)


class WorkOrderTransitionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        workorder = get_object_or_404(visible_workorders_queryset(request.user), pk=pk)
        target_status = request.POST.get("status", "")
        if not can_transition(request.user, workorder, target_status):
            return HttpResponseForbidden("Переход запрещен")
        transition_workorder(
            workorder=workorder, user=request.user, to_status=target_status
        )
        workorder.refresh_from_db()
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
            response = render(
                request,
                "workorders/partials/status_section.html",
                _stepper_context(request.user, workorder),
            )
            return _mark_workorders_changed(response)
        messages.success(request, "Статус заявки обновлен.")
        return redirect("workorders:detail", pk=workorder.pk)


class WorkOrderBoardMoveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        workorder = get_object_or_404(visible_workorders_queryset(request.user), pk=pk)
        old_status = workorder.status
        column_code = request.POST.get("column", "").strip()
        column = get_object_or_404(KanbanColumnConfig, code=column_code, board=workorder.board)
        target_status = drop_status_for_column(request.user, workorder, column)

        if target_status:
            transition_workorder(
                workorder=workorder, user=request.user, to_status=target_status
            )
        elif workorder.status not in column.statuses:
            return HttpResponseForbidden("Перемещение в колонку запрещено")

        # Determine which columns to update
        board_view = WorkOrderBoardView()
        board_view.request = request
        board_view.args = ()
        board_view.kwargs = {}
        context = board_view.get_context_data()

        # Find the old column and the new column configs
        updated_columns = []
        # We need to find the column key for the old status
        status_to_column = {}
        column_configs = configured_columns(board=workorder.board)
        for cfg in column_configs:
            for s in cfg.statuses:
                status_to_column[s] = cfg.code

        old_column_key = status_to_column.get(old_status)
        new_column_key = column.code

        for col in context["board_columns"]:
            if col["key"] == old_column_key or col["key"] == new_column_key:
                updated_columns.append(col)

        # Render only the affected columns with is_oob=True
        response_html = ""
        for col in updated_columns:
            response_html += render(
                request,
                "workorders/partials/kanban_column.html",
                {**context, "column": col, "is_oob": True},
            ).content.decode("utf-8")

        from django.http import HttpResponse

        return HttpResponse(response_html)


class WorkOrderConfirmClosureView(LoginRequiredMixin, View):
    def post(self, request, pk):
        workorder = get_object_or_404(visible_workorders_queryset(request.user), pk=pk)
        if not can_confirm_closure(request.user, workorder):
            return HttpResponseForbidden("Подтверждение закрытия запрещено")
        confirm_closure(workorder=workorder, user=request.user)
        workorder.refresh_from_db()
        context = _stepper_context(request.user, workorder)
        if request.htmx:
            response = render(request, "workorders/partials/status_section.html", context)
            return _mark_workorders_changed(response)
        messages.success(request, "Закрытие заявки подтверждено.")
        return redirect("workorders:detail", pk=workorder.pk)


class WorkOrderRateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        workorder = get_object_or_404(visible_workorders_queryset(request.user), pk=pk)
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
                response = render(
                    request, "workorders/partials/rating_section.html", context
                )
                return _mark_workorders_changed(response)
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
        if not can_manage_board_columns(request.user):
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
        if not can_manage_board_columns(request.user):
            return HttpResponseForbidden("Изменение колонок запрещено")
        column = get_object_or_404(KanbanColumnConfig, pk=pk)
        return render(
            request,
            "workorders/partials/column_config_form.html",
            column_card_context(column),
        )


class KanbanColumnDisplayView(LoginRequiredMixin, View):
    def get(self, request, pk):
        if not can_manage_board_columns(request.user):
            return HttpResponseForbidden("Изменение колонок запрещено")
        column = get_object_or_404(KanbanColumnConfig, pk=pk)
        return render(
            request,
            "workorders/partials/column_config_card.html",
            column_card_context(column),
        )
