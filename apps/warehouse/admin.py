from django.contrib import admin

from .models import (
    FundingSource,
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StockEntry,
    StockLot,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
    WarehouseAuditEvent,
    WarehouseImportIssue,
    WarehouseImportRecord,
    WarehouseImportRun,
    WarehouseItem,
    WarehouseItemCategory,
    WarehouseReportProfile,
)


class WarehouseBreakGlassAdmin(admin.ModelAdmin):
    """Резервный superuser-only доступ; штатная работа выполняется в разделе склада."""

    def has_module_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)


class ReadOnlyWarehouseAdmin(WarehouseBreakGlassAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class StockDocumentLineInline(admin.TabularInline):
    model = StockDocumentLine
    extra = 0
    can_delete = False
    readonly_fields = [field.name for field in StockDocumentLine._meta.fields]


@admin.register(StockDocument)
class StockDocumentAdmin(ReadOnlyWarehouseAdmin):
    list_display = ("operation_date", "document_type", "number", "department", "status")
    list_filter = ("status", "document_type", "department")
    inlines = [StockDocumentLineInline]


@admin.register(StockEntry, StockBalance, WarehouseAuditEvent, WarehouseImportRecord)
class LedgerAdmin(ReadOnlyWarehouseAdmin):
    list_per_page = 100


@admin.register(WarehouseImportRun)
class ImportRunAdmin(ReadOnlyWarehouseAdmin):
    list_display = ("run_id", "source_name", "adapter", "status", "created_at")


@admin.register(WarehouseImportIssue)
class ImportIssueAdmin(ReadOnlyWarehouseAdmin):
    list_display = ("run", "severity", "code", "source_table", "resolved_at")
    list_filter = ("severity", "code")


for model in (
    FundingSource,
    StockLot,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
    WarehouseItem,
    WarehouseItemCategory,
    WarehouseReportProfile,
):
    admin.site.register(model, WarehouseBreakGlassAdmin)
