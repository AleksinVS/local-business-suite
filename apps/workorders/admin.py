from django.contrib import admin

from .models import KanbanColumnConfig, WorkOrder, WorkOrderAttachment, WorkOrderComment, WorkOrderTransitionLog


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


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ("number", "title", "department", "status", "priority", "assignee")
    list_filter = ("status", "priority", "department")
    search_fields = ("number", "title", "description", "device__name", "device__serial_number")
    inlines = [WorkOrderCommentInline, WorkOrderAttachmentInline, WorkOrderTransitionLogInline]


@admin.register(KanbanColumnConfig)
class KanbanColumnConfigAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "position")
    ordering = ("position", "id")
