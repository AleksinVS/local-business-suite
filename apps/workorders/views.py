from collections import OrderedDict
import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q

User = get_user_model()
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, TemplateView, UpdateView

from . import notification_events
from .department_filter import (
    build_department_filter_read_model,
    department_search_ids,
)
from .forms import (
    KanbanColumnTitleForm,
    WorkOrderAttachmentForm,
    WorkOrderCommentForm,
    WorkOrderForm,
    WorkOrderRatingForm,
    WorkOrderUpdateForm,
    department_choice_label,
    device_choice_label,
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
    can_access_workorders,
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
    _is_actor_snapshot,
    _resolve_visible_department_device_selection_for_actor,
    _visible_boards_queryset_for_actor,
    _visible_workorders_queryset_for_actor,
    creation_departments_queryset,
    creation_devices_queryset,
    resolve_active_actor,
    visible_boards_queryset,
    visible_workorders_queryset,
)
from .services import (
    add_workorder_attachment_command,
    add_workorder_comment_command,
    confirm_workorder_closure_command,
    create_workorder_command,
    move_workorder_command,
    rate_workorder_command,
    transition_workorder_command,
    update_board_column_command,
    update_workorder_command,
)


VIEW_BOARD = "board"


def _policy_actor(user):
    """Reuse only a marked actor snapshot inside one render operation."""

    if _is_actor_snapshot(user):
        return user
    return resolve_active_actor(user, force_refresh=True)


def quick_transition_choices_for(user, workorder):
    user = _policy_actor(user)
    if user is None:
        return []
    return [
        (status, label)
        for status, label in WorkOrderStatus.choices
        if can_transition(user, workorder, status)
    ]


def _stepper_context(user, workorder):
    user = _policy_actor(user)
    if user is None:
        return {
            "workorder": workorder,
            "transition_choices": [],
            "transition_choices_vals": set(),
            "status_choices": WorkOrderStatus.choices,
            "can_confirm_closure": False,
        }
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
    user = _policy_actor(user)
    if user is None:
        return None
    if workorder.status in column.statuses:
        return None
    for status in column.statuses:
        if can_transition(user, workorder, status):
            return status
    return None


def _fresh_render_actor_and_workorder(request, workorder_id):
    """Re-authorize a target immediately before an HTMX fragment render."""
    actor = resolve_active_actor(request.user, force_refresh=True)
    if actor is None:
        raise PermissionDenied("Учетная запись отключена.")
    workorder = _visible_workorders_queryset_for_actor(actor).filter(
        pk=workorder_id
    ).first()
    if workorder is None:
        raise PermissionDenied("Заявка больше недоступна текущему пользователю.")
    return actor, workorder


def column_card_context(column):
    return {
        "column_config": column,
        "rename_form": KanbanColumnTitleForm(instance=column),
    }


def page_context_json(payload):
    return json.dumps(payload, ensure_ascii=False)


def _filter_values(request, key):
    return [value for value in request.GET.getlist(key) if value]


def _positive_id(raw_value):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _workorder_status_color_style():
    from apps.core.contract_store import get_contract
    from apps.core.status_colors import status_color_css_variables

    return status_color_css_variables(
        get_contract("workorder_status_colors"),
        prefix="workorder-status",
    )


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


def workorders_board_page_context(
    request,
    board,
    department_values=(),
    device_values=(),
):
    return {
        "schema_version": "1",
        "page": {
            "path": request.path,
            "title": "Канбан заявок",
            "module": "workorders",
            "view": VIEW_BOARD,
        },
        "selection": {},
        "filters": {
            "board": board.slug if board else "",
            "q": request.GET.get("q", ""),
            "department": [str(value) for value in department_values],
            "status": _filter_values(request, "status"),
            "assignee": _filter_values(request, "assignee"),
            "device": [str(value) for value in device_values],
        },
        "ui_state": {"focused_region": "board"},
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
            "display": workorder.display_name,
        },
        "filters": {},
        "ui_state": {"right_drawer": "open", "focused_region": "detail_panel"},
    }


class WorkOrderBoardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "workorders/board.html"

    def test_func(self):
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        return actor is not None and can_access_workorders(actor)

    def get(self, request, *args, **kwargs):
        request.session.pop("workorders:view_mode", None)
        department_selection = self.get_department_selection()
        canonical_url = self._canonical_filter_url(department_selection)
        normalized_department_values = [
            str(value) for value in department_selection.selected_department_ids
        ]
        normalized_device_values = [
            str(value) for value in department_selection.selected_device_ids
        ]
        needs_canonical_url = (
            "view" in request.GET
            or request.GET.getlist("department")
            != normalized_department_values
            or request.GET.getlist("device") != normalized_device_values
        )
        if needs_canonical_url and not request.htmx:
            return redirect(canonical_url)

        response = super().get(request, *args, **kwargs)
        if needs_canonical_url:
            response["HX-Replace-Url"] = canonical_url
        return response

    def _canonical_filter_url(self, department_selection):
        query = self.request.GET.copy()
        query.pop("view", None)
        if department_selection.selected_department_ids:
            query.setlist(
                "department",
                [
                    str(value)
                    for value in department_selection.selected_department_ids
                ],
            )
        else:
            query.pop("department", None)
        if department_selection.selected_device_ids:
            query.setlist(
                "device",
                [str(value) for value in department_selection.selected_device_ids],
            )
        else:
            query.pop("device", None)
        encoded_query = query.urlencode()
        if encoded_query:
            return f"{self.request.path}?{encoded_query}"
        return self.request.path

    def get_department_selection(self):
        if not hasattr(self, "_department_selection"):
            actor = _policy_actor(getattr(self, "_actor", self.request.user))
            self._actor = actor
            self._department_selection = _resolve_visible_department_device_selection_for_actor(
                actor,
                self.request.GET.getlist("department"),
                self.request.GET.getlist("device"),
            )
        return self._department_selection

    def get_board(self):
        slug = self.kwargs.get("board_slug")
        boards = self.get_visible_boards()
        if slug:
            return get_object_or_404(boards, slug=slug)
        board = boards.first()
        return board

    def get_visible_boards(self):
        if not hasattr(self, "_visible_boards"):
            actor = _policy_actor(getattr(self, "_actor", self.request.user))
            self._visible_boards = _visible_boards_queryset_for_actor(actor)
        return self._visible_boards

    def get_queryset(self, board):
        actor = _policy_actor(getattr(self, "_actor", self.request.user))
        queryset = _visible_workorders_queryset_for_actor(actor, board=board).order_by(
            "-updated_at"
        )
        queryset = queryset.annotate(
            comment_count=Count("comments", distinct=True),
            attachment_count=Count("attachments", distinct=True),
        )
        q = self.request.GET.get("q", "").strip()
        department_selection = self.get_department_selection()
        status_values = _filter_values(self.request, "status")
        assignees = _filter_values(self.request, "assignee")

        if q:
            matched_department_ids = department_search_ids(
                q,
                department_selection.visible_departments,
            )
            search_filter = (
                Q(number__icontains=q)
                | Q(title__icontains=q)
                | Q(description__icontains=q)
                | Q(device__name__icontains=q)
                | Q(device__model__icontains=q)
                | Q(device__serial_number__icontains=q)
                | Q(device__inventory_number__icontains=q)
                | _related_user_search_q("author", q)
                | _related_user_search_q("assignee", q)
            )
            if matched_department_ids:
                search_filter |= Q(department_id__in=matched_department_ids)
            queryset = queryset.filter(search_filter)
        if (
            department_selection.selected_department_ids
            or department_selection.selected_device_ids
        ):
            tree_filter = Q()
            if department_selection.selected_department_ids:
                tree_filter |= Q(
                    department_id__in=department_selection.branch_ids
                )
            if department_selection.selected_device_ids:
                tree_filter |= Q(
                    device_id__in=department_selection.selected_device_ids
                )
            queryset = queryset.filter(tree_filter)
        if status_values:
            queryset = queryset.filter(status__in=status_values)
        if assignees:
            queryset = queryset.filter(assignee__id__in=assignees)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        actor = _policy_actor(getattr(self, "_actor", self.request.user))
        if actor is None:
            context.update({"no_boards": True, "current_view": VIEW_BOARD})
            return context
        self._actor = actor
        board = self.get_board()
        department_selection = self.get_department_selection()
        context["page_ai_context_json"] = page_context_json(
            workorders_board_page_context(
                self.request,
                board,
                department_values=department_selection.selected_department_ids,
                device_values=department_selection.selected_device_ids,
            )
        )
        department_nodes = build_department_filter_read_model(
            department_selection.visible_departments,
            department_selection.selected_department_ids,
            department_selection.visible_devices,
            department_selection.selected_device_ids,
        )
        context["departments"] = department_selection.visible_departments
        context["department_filter"] = {
            "nodes": department_nodes,
            "selected_ids": department_selection.selected_department_ids,
            "selected_department_ids": department_selection.selected_department_ids,
            "selected_device_ids": department_selection.selected_device_ids,
            "selected_count": department_selection.selected_count,
            "can_create_workorder": can_create(actor),
            "is_empty": not department_nodes,
        }
        context["visible_boards"] = self.get_visible_boards()
        context["workorder_status_color_style"] = _workorder_status_color_style()
        context["status_choices"] = WorkOrderStatus.choices
        visible_assignee_ids = _visible_workorders_queryset_for_actor(actor).filter(
            assignee__isnull=False
        ).values("assignee_id")
        # Filter candidates from the current visible workorders only.  The
        # command deliberately still permits any active target on write: that
        # is the existing manage_assignments product semantic, not a new
        # capability or a broader read selector.
        context["assignees"] = User.objects.filter(
            is_active=True,
            pk__in=visible_assignee_ids,
        ).order_by("first_name", "username")
        context["filters"] = {
            "view": VIEW_BOARD,
            "q": self.request.GET.get("q", ""),
            "department_values": [
                str(value) for value in department_selection.selected_ids
            ],
            "status_values": _filter_values(self.request, "status"),
            "assignee_values": _filter_values(self.request, "assignee"),
            "device_values": [
                str(value) for value in department_selection.selected_device_ids
            ],
        }
        context["can_create_workorder"] = can_create(actor)
        context["can_manage_board_columns"] = can_manage_board_columns(
            actor
        )
        if not board:
            context["no_boards"] = True
            context["current_view"] = VIEW_BOARD
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
                    drop_status_for_column(actor, workorder, column)
                ]
                if status
            }
            columns[column_code]["items"].append(
                {
                    "workorder": workorder,
                    "quick_transitions": quick_transition_choices_for(
                        actor, workorder
                    ),
                    "can_confirm_closure": can_confirm_closure(
                        actor, workorder
                    ),
                    "can_drag": bool(drop_targets),
                }
            )
        board_column_count = len(columns) if columns else 1
        context["current_board"] = board
        context["current_view"] = VIEW_BOARD
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
        return context

    def get_template_names(self):
        if self.request.htmx and self.request.htmx.target == "detail-panel":
            return ["workorders/partials/detail_panel_empty.html"]
        if self.request.htmx and self.request.htmx.target == "board-columns":
            return ["workorders/partials/board_columns.html"]
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
        user_department_id = self.request.user.department_id
        if user_department_id and creation_departments_queryset(self.request.user).filter(
            pk=user_department_id
        ).exists():
            initial["department"] = user_department_id
        department_id = _positive_id(self.request.GET.get("department"))
        if department_id and creation_departments_queryset(self.request.user).filter(
            pk=department_id
        ).exists():
            initial["department"] = department_id
        device_id = _positive_id(self.request.GET.get("device"))
        if device_id:
            device = (
                creation_devices_queryset(self.request.user)
                .filter(pk=device_id)
                .first()
            )
            if device:
                initial["device"] = device.pk
                initial["department"] = device.department_id
                initial["description"] = device.name
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Creation scope is intentionally separate from the relational read
        # directory: it is the actor's own allowed organizational branch.
        form.fields["department"].queryset = creation_departments_queryset(
            self.request.user
        )
        form.fields["device"].queryset = creation_devices_queryset(
            self.request.user
        )
        return form

    def get_template_names(self):
        if self.request.htmx:
            return ["workorders/partials/workorder_form_partial.html"]
        return [self.template_name]

    def get_success_url(self):
        if self.request.htmx:
            if self.object and self.object.board_id:
                return reverse(
                    "workorders:board_specific",
                    kwargs={"board_slug": self.object.board.slug},
                )
            return reverse("workorders:board")
        return reverse("workorders:detail", kwargs={"pk": self.object.pk})

    def dispatch(self, request, *args, **kwargs):
        actor = resolve_active_actor(request.user, force_refresh=True)
        if actor is None or not can_create(actor):
            return HttpResponseForbidden("Создание заявок запрещено")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = create_workorder_command(
            actor=self.request.user,
            payload=form.cleaned_data,
        )
        if self.request.htmx:
            response = HttpResponse(status=204)
            response["HX-Redirect"] = self.get_success_url()
            return response
        messages.success(self.request, "Заявка создана.")
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["return_view"] = VIEW_BOARD
        form = context["form"]
        board_id = _positive_id(form["board"].value())
        department_id = _positive_id(form["department"].value())
        device_id = _positive_id(form["device"].value())
        board = (
            form.fields["board"].queryset.filter(pk=board_id).first()
            if board_id
            else None
        )
        department = None
        device = None
        if department_id:
            department = creation_departments_queryset(self.request.user).filter(
                pk=department_id
            ).first()
        if device_id:
            device = creation_devices_queryset(self.request.user).filter(
                pk=device_id
            ).first()
        context["selected_department_label"] = (
            department_choice_label(department) if department else ""
        )
        context["selected_board_label"] = board.title if board else ""
        context["selected_device_label"] = (
            device_choice_label(device) if device else ""
        )
        context["selected_device_department_id"] = (
            device.department_id if device else ""
        )
        return context


class WorkOrderUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = WorkOrder
    form_class = WorkOrderUpdateForm
    template_name = "workorders/workorder_form.html"

    def get_queryset(self):
        return visible_workorders_queryset(self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_template_names(self):
        if self.request.htmx:
            return ["workorders/partials/workorder_edit_form_partial.html"]
        return [self.template_name]

    def test_func(self):
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        return actor is not None and can_edit(actor, self.get_object())

    def form_valid(self, form):
        previous = WorkOrder.objects.get(pk=form.instance.pk)
        changed_fields = set(form.changed_data)
        previous_assignee_id = previous.assignee_id
        self.object = update_workorder_command(
            actor=self.request.user,
            workorder_id=form.instance.pk,
            payload={
                field: form.cleaned_data[field]
                for field in form.changed_data
            },
        )
        notification_events.notify_workorder_updated(
            self.object,
            actor=self.request.user,
            changed_fields=changed_fields,
            previous_assignee_id=previous_assignee_id,
        )
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
        return redirect(self.get_success_url())

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        actor = resolve_active_actor(self.request.user, force_refresh=True)
        if actor is None or not can_manage_assignments(actor):
            form.fields["assignee"].disabled = True
            form.fields["assignee"].required = False
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        workorder = self.get_object()
        context["workorder"] = workorder
        form = context["form"]

        def selected_object(field_name):
            value = _positive_id(form[field_name].value())
            if not value:
                return None
            return form.fields[field_name].queryset.filter(pk=value).first()

        board = selected_object("board")
        department = selected_object("department")
        device = selected_object("device")
        assignee = selected_object("assignee")
        context["selected_board_label"] = board.title if board else ""
        context["selected_department_label"] = (
            department_choice_label(department) if department else ""
        )
        context["selected_device_label"] = (
            device_choice_label(device) if device else ""
        )
        context["selected_device_department_id"] = (
            device.department_id if device else ""
        )
        context["selected_assignee_label"] = (
            (assignee.get_full_name() or assignee.username) if assignee else ""
        )
        context["current_device_id"] = device.pk if device else ""
        context["current_assignee_id"] = assignee.pk if assignee else ""
        context["current_workorder_id"] = workorder.pk
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
        actor, visible_workorder = _fresh_render_actor_and_workorder(
            self.request, self.object.pk
        )
        self.object = visible_workorder
        context = super().get_context_data(**kwargs)
        context["comment_form"] = WorkOrderCommentForm()
        context["attachment_form"] = WorkOrderAttachmentForm()
        context["rating_form"] = WorkOrderRatingForm(instance=self.object)
        context.update(_stepper_context(actor, self.object))
        context["can_edit"] = can_edit(actor, self.object)
        context["can_confirm_closure"] = can_confirm_closure(
            actor, self.object
        )
        context["can_rate"] = can_rate(actor, self.object)
        context["can_upload_attachment"] = can_upload_attachment(
            actor, self.object
        )
        context["can_comment"] = can_comment(actor, self.object)
        context["detail_ai_context_json"] = page_context_json(
            workorder_detail_page_context(self.request, self.object)
        )
        return context


class WorkOrderCommentCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        # Resolve the target through the scoped selector even when form data
        # is invalid, so the error branch cannot reference an undefined or
        # foreign workorder.
        workorder = get_object_or_404(visible_workorders_queryset(request.user), pk=pk)
        form = WorkOrderCommentForm(request.POST)
        if form.is_valid():
            try:
                comment = add_workorder_comment_command(
                    actor=request.user,
                    workorder_id=pk,
                    body=form.cleaned_data["body"],
                )
            except PermissionDenied:
                return HttpResponseForbidden("Комментарии недоступны")
            workorder = comment.workorder
            workorder.refresh_from_db()
            if request.htmx:
                try:
                    _actor, workorder = _fresh_render_actor_and_workorder(request, pk)
                except PermissionDenied:
                    return HttpResponseForbidden("Комментарии недоступны")
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
            try:
                _actor, workorder = _fresh_render_actor_and_workorder(request, pk)
            except PermissionDenied:
                return HttpResponseForbidden("Комментарии недоступны")
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
        # See comment form: invalid transport data still uses a scoped target.
        workorder = get_object_or_404(visible_workorders_queryset(request.user), pk=pk)
        form = WorkOrderAttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                attachment = add_workorder_attachment_command(
                    actor=request.user,
                    workorder_id=pk,
                    uploaded_file=form.cleaned_data["file"],
                )
            except PermissionDenied:
                return HttpResponseForbidden("Загрузка файлов запрещена")
            workorder = attachment.workorder
            workorder.refresh_from_db()
            if request.htmx:
                try:
                    actor, workorder = _fresh_render_actor_and_workorder(request, pk)
                except PermissionDenied:
                    return HttpResponseForbidden("Загрузка файлов запрещена")
                response = render(
                    request,
                    "workorders/partials/attachments.html",
                    {
                        "workorder": workorder,
                        "attachment_form": WorkOrderAttachmentForm(),
                        "can_upload_attachment": can_upload_attachment(actor, workorder),
                    },
                )
                return _mark_workorders_changed(response)
            messages.success(request, "Файл добавлен.")
            return redirect("workorders:detail", pk=workorder.pk)
        if request.htmx:
            try:
                actor, workorder = _fresh_render_actor_and_workorder(request, pk)
            except PermissionDenied:
                return HttpResponseForbidden("Загрузка файлов запрещена")
            return render(
                request,
                "workorders/partials/attachments.html",
                {
                    "workorder": workorder,
                    "attachment_form": form,
                    "can_upload_attachment": can_upload_attachment(actor, workorder),
                },
                status=400,
            )
        messages.error(request, "Не удалось загрузить файл.")
        return redirect("workorders:detail", pk=workorder.pk)


class WorkOrderTransitionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        target_status = request.POST.get("status", "")
        try:
            workorder = transition_workorder_command(
                actor=request.user,
                workorder_id=pk,
                target_status=target_status,
            )
        except PermissionDenied:
            return HttpResponseForbidden("Переход запрещен")
        workorder.refresh_from_db()
        if request.htmx:
            try:
                actor, workorder = _fresh_render_actor_and_workorder(request, pk)
            except PermissionDenied:
                return HttpResponseForbidden("Переход запрещен")
            if request.htmx.target == "board-columns":
                board_view = WorkOrderBoardView()
                board_view.request = request
                board_view.args = ()
                board_view.kwargs = {}
                board_view._actor = actor
                board_context = board_view.get_context_data()
                if not board_context.get("board_columns"):
                    return HttpResponseForbidden("Доска заявки больше недоступна")
                return render(
                    request,
                    "workorders/partials/board_columns.html",
                    board_context,
                )
            response = render(
                request,
                "workorders/partials/status_section.html",
                _stepper_context(actor, workorder),
            )
            return _mark_workorders_changed(response)
        messages.success(request, "Статус заявки обновлен.")
        return redirect("workorders:detail", pk=workorder.pk)


class WorkOrderBoardMoveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        column_code = request.POST.get("column", "").strip()
        try:
            workorder, old_status, column = move_workorder_command(
                actor=request.user,
                workorder_id=pk,
                column_code=column_code,
            )
        except PermissionDenied:
            return HttpResponseForbidden("Перемещение в колонку запрещено")

        try:
            actor, visible_workorder = _fresh_render_actor_and_workorder(request, pk)
        except PermissionDenied:
            return HttpResponseForbidden("Перемещение в колонку запрещено")
        if visible_workorder.board_id != workorder.board_id:
            return HttpResponseForbidden("Доска заявки больше недоступна")

        # Determine which columns to update only after re-authorizing the
        # actor and target immediately before rendering.
        board_view = WorkOrderBoardView()
        board_view.request = request
        board_view.args = ()
        board_view.kwargs = {}
        board_view._actor = actor
        context = board_view.get_context_data()
        if actor is None or not context.get("board_columns"):
            return HttpResponseForbidden("Доска заявки больше недоступна")

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

        for col in context.get("board_columns", []):
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
        try:
            workorder = confirm_workorder_closure_command(
                actor=request.user,
                workorder_id=pk,
            )
        except PermissionDenied:
            return HttpResponseForbidden("Подтверждение закрытия запрещено")
        workorder.refresh_from_db()
        try:
            actor, workorder = _fresh_render_actor_and_workorder(request, pk)
        except PermissionDenied:
            return HttpResponseForbidden("Подтверждение закрытия запрещено")
        context = _stepper_context(actor, workorder)
        if request.htmx:
            response = render(request, "workorders/partials/status_section.html", context)
            return _mark_workorders_changed(response)
        messages.success(request, "Закрытие заявки подтверждено.")
        return redirect("workorders:detail", pk=workorder.pk)


class WorkOrderRateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        workorder = visible_workorders_queryset(request.user).filter(pk=pk).first()
        if workorder is None:
            return HttpResponseForbidden("Оценка запрещена")
        form = WorkOrderRatingForm(request.POST)
        if form.is_valid():
            try:
                workorder = rate_workorder_command(
                    actor=request.user,
                    workorder_id=pk,
                    rating=form.cleaned_data["rating"],
                )
            except PermissionDenied:
                return HttpResponseForbidden("Оценка запрещена")
            workorder.refresh_from_db()
            try:
                actor, workorder = _fresh_render_actor_and_workorder(request, pk)
            except PermissionDenied:
                return HttpResponseForbidden("Оценка запрещена")
            context = {
                "workorder": workorder,
                "rating_form": WorkOrderRatingForm(instance=workorder),
                "can_rate": actor is not None and can_rate(actor, workorder),
            }
            if request.htmx:
                response = render(
                    request, "workorders/partials/rating_section.html", context
                )
                return _mark_workorders_changed(response)
            messages.success(request, "Оценка сохранена.")
            return redirect("workorders:detail", pk=workorder.pk)
        if request.htmx:
            try:
                actor, workorder = _fresh_render_actor_and_workorder(request, pk)
            except PermissionDenied:
                return HttpResponseForbidden("Оценка запрещена")
            return render(
                request,
                "workorders/partials/rating_section.html",
                {
                    "workorder": workorder,
                    "rating_form": form,
                    "can_rate": actor is not None and can_rate(actor, workorder),
                },
                status=400,
            )
        messages.error(request, "Не удалось сохранить оценку.")
        return redirect("workorders:detail", pk=workorder.pk)


class KanbanColumnRenameView(LoginRequiredMixin, View):
    def post(self, request, pk):
        column = get_object_or_404(
            KanbanColumnConfig.objects.filter(
                board__in=visible_boards_queryset(request.user)
            ),
            pk=pk,
        )
        form = KanbanColumnTitleForm(request.POST, instance=column)
        if form.is_valid():
            try:
                column = update_board_column_command(
                    actor=request.user,
                    column_id=pk,
                    payload=form.cleaned_data,
                )
            except PermissionDenied:
                return HttpResponseForbidden("Изменение колонок запрещено")
        actor = resolve_active_actor(request.user, force_refresh=True)
        if actor is None or not _visible_boards_queryset_for_actor(actor).filter(
            pk=column.board_id
        ).exists():
            return HttpResponseForbidden("Изменение колонок запрещено")
        board_view = WorkOrderBoardView()
        board_view.request = request
        board_view.args = ()
        board_view.kwargs = {}
        board_view._actor = actor
        if request.htmx and request.htmx.target == f"column-config-{column.pk}":
            return render(
                request,
                "workorders/partials/column_config_card.html",
                column_card_context(column),
                status=200 if form.is_valid() else 400,
            )
        board_context = board_view.get_context_data()
        if not board_context.get("board_columns"):
            return HttpResponseForbidden("Доска больше недоступна")
        return render(
            request,
            "workorders/partials/board_columns.html",
            board_context,
            status=200 if form.is_valid() else 400,
        )


class KanbanColumnEditView(LoginRequiredMixin, View):
    def get(self, request, pk):
        actor = resolve_active_actor(request.user, force_refresh=True)
        if actor is None or not can_manage_board_columns(actor):
            return HttpResponseForbidden("Изменение колонок запрещено")
        column = get_object_or_404(
            KanbanColumnConfig.objects.filter(
                board__in=visible_boards_queryset(request.user)
            ),
            pk=pk,
        )
        return render(
            request,
            "workorders/partials/column_config_form.html",
            column_card_context(column),
        )


class KanbanColumnDisplayView(LoginRequiredMixin, View):
    def get(self, request, pk):
        actor = resolve_active_actor(request.user, force_refresh=True)
        if actor is None or not can_manage_board_columns(actor):
            return HttpResponseForbidden("Изменение колонок запрещено")
        column = get_object_or_404(
            KanbanColumnConfig.objects.filter(
                board__in=visible_boards_queryset(request.user)
            ),
            pk=pk,
        )
        return render(
            request,
            "workorders/partials/column_config_card.html",
            column_card_context(column),
        )
