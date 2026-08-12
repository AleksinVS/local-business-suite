from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from .forms import BoardAccessForm
from .models import (
    Board,
    BoardAccessAudit,
    KanbanColumnConfig,
    WorkOrder,
    WorkOrderAttachment,
    WorkOrderComment,
    WorkOrderTransitionLog,
)
from .policies import board_access_role_names
from .services import apply_board_access, clone_board, preview_board_access


class WorkOrderCommentInline(admin.TabularInline):
    model = WorkOrderComment
    extra = 0


class WorkOrderAttachmentInline(admin.TabularInline):
    model = WorkOrderAttachment
    extra = 0


class WorkOrderTransitionLogInline(admin.TabularInline):
    model = WorkOrderTransitionLog
    extra = 0
    readonly_fields = ("from_status", "to_status", "actor", "created_at")


class KanbanColumnConfigInline(admin.TabularInline):
    model = KanbanColumnConfig
    extra = 1
    ordering = ("position",)


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "created_at")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("allowed_groups", "access_management_link")
    inlines = [KanbanColumnConfigInline]
    actions = ["clone_boards"]

    @admin.display(description="Резервное управление доступом")
    def access_management_link(self, obj):
        if not obj or not obj.pk:
            return "Сначала сохраните доску."
        return format_html(
            '<a href="{}">Открыть защищённый сценарий изменения</a>',
            reverse("admin:workorders_board_access", args=[obj.pk]),
        )

    def get_urls(self):
        return [
            path(
                "<path:object_id>/access/",
                self.admin_site.admin_view(self.board_access_view),
                name="workorders_board_access",
            )
        ] + super().get_urls()

    def board_access_view(self, request, object_id):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied("Резервное изменение доступно только активному суперпользователю.")
        board = get_object_or_404(Board, pk=object_id)
        source = BoardAccessAudit.Source.DJANGO_ADMIN_BREAK_GLASS
        preview = None
        if request.method == "POST":
            form = BoardAccessForm(request.POST, source=source)
            if form.is_valid():
                selected = form.cleaned_data["group_names"]
                reason = form.cleaned_data["reason"]
                try:
                    if request.POST.get("action") == "preview":
                        preview = preview_board_access(
                            actor=request.user,
                            board=board,
                            selected_group_names=selected,
                            reason=reason,
                            source=source,
                        )
                        form = BoardAccessForm(
                            source=source,
                            initial={
                                "group_names": selected,
                                "reason": reason,
                                "preview_token": preview["preview_token"],
                            },
                        )
                    else:
                        board, audit = apply_board_access(
                            actor=request.user,
                            board=board,
                            selected_group_names=selected,
                            preview_token=form.cleaned_data["preview_token"],
                            risk_confirmed=form.cleaned_data["risk_confirmed"],
                            reason=reason,
                            source=source,
                        )
                        self.message_user(
                            request,
                            f"Доступ к доске изменён. Предметный аудит #{audit.pk}.",
                            level=messages.SUCCESS,
                        )
                        return redirect("admin:workorders_board_change", object_id=board.pk)
                except ValidationError as exc:
                    form.add_error(None, exc)
        else:
            form = BoardAccessForm(
                source=source,
                initial={
                    "group_names": list(
                        board.allowed_groups.order_by("name").values_list("name", flat=True)
                    )
                },
            )
        return render(
            request,
            "settings_center/board_access_form.html",
            {
                "board": board,
                "form": form,
                "preview": preview,
                "history": board.access_audits.select_related("actor")[:8],
                "return_url": reverse("admin:workorders_board_change", args=[board.pk]),
                "is_break_glass": True,
                "legacy_group_names": sorted(
                    set(board.allowed_groups.values_list("name", flat=True))
                    - set(board_access_role_names())
                ),
            },
        )

    @admin.action(description="Клонировать выбранные доски")
    def clone_boards(self, request, queryset):
        for board in queryset:
            try:
                clone_board(
                    actor=request.user,
                    board=board,
                    reason=f"Копирование из Django Admin доски #{board.pk}",
                )
            except (PermissionDenied, ValidationError) as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
                return
        self.message_user(
            request,
            f"Выбранные доски ({queryset.count()}) скопированы без доступа. "
            "Назначьте роли через защищённый сценарий каждой новой доски.",
        )


@admin.register(BoardAccessAudit)
class BoardAccessAuditAdmin(admin.ModelAdmin):
    list_display = ("board", "actor", "source", "created_at")
    list_filter = ("source", "created_at")
    search_fields = ("board__title", "actor__username")
    readonly_fields = [field.name for field in BoardAccessAudit._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ("number", "title", "board", "department", "status", "priority", "assignee")
    list_filter = ("board", "status", "priority", "department")
    search_fields = (
        "number",
        "title",
        "description",
        "device__name",
        "device__inventory_number",
        "device__serial_number",
        "department__name",
    )
    inlines = [WorkOrderCommentInline, WorkOrderAttachmentInline, WorkOrderTransitionLogInline]


@admin.register(KanbanColumnConfig)
class KanbanColumnConfigAdmin(admin.ModelAdmin):
    list_display = ("title", "board", "code", "position")
    list_filter = ("board",)
    ordering = ("board", "position", "id")
