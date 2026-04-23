from django.contrib import admin

from .models import (
    Board,
    KanbanColumnConfig,
    WorkOrder,
    WorkOrderAttachment,
    WorkOrderComment,
    WorkOrderTransitionLog,
)


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
    filter_horizontal = ("allowed_groups",)
    inlines = [KanbanColumnConfigInline]
    actions = ["clone_boards"]

    @admin.action(description="Клонировать выбранные доски")
    def clone_boards(self, request, queryset):
        for board in queryset:
            board.clone()
        self.message_user(request, f"Выбранные доски ({queryset.count()}) успешно скопированы.")


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ("number", "title", "board", "department", "status", "priority", "assignee")
    list_filter = ("board", "status", "priority", "department")
    search_fields = ("number", "title", "description", "device__name", "device__serial_number", "department__name")
    inlines = [WorkOrderCommentInline, WorkOrderAttachmentInline, WorkOrderTransitionLogInline]


@admin.register(KanbanColumnConfig)
class KanbanColumnConfigAdmin(admin.ModelAdmin):
    list_display = ("title", "board", "code", "position")
    list_filter = ("board",)
    ordering = ("board", "position", "id")
