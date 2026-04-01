from django.contrib import admin

from .models import WaitingListAuditLog, WaitingListEntry


class WaitingListAuditLogInline(admin.TabularInline):
    model = WaitingListAuditLog
    extra = 0
    readonly_fields = ("actor", "action", "created_at")
    ordering = ("-created_at",)


@admin.register(WaitingListEntry)
class WaitingListEntryAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "patient_name",
        "service_id",
        "status",
        "priority_cito",
        "date_tag",
        "created_at",
    )
    list_filter = ("status", "priority_cito", "service_id", "created_at")
    search_fields = ("patient_name", "patient_dob", "patient_phone", "comment")
    readonly_fields = ("external_id", "created_at", "updated_at")
    inlines = [WaitingListAuditLogInline]

    fieldsets = (
        (None, {
            "fields": ("external_id", "patient_name", "patient_dob", "patient_phone"),
        }),
        ("Услуга и сроки", {
            "fields": ("service_id", "date_tag", "date_end", "priority_cito"),
        }),
        ("Статус и история", {
            "fields": ("status", "comment", "created_at", "updated_at"),
        }),
    )


@admin.register(WaitingListAuditLog)
class WaitingListAuditLogAdmin(admin.ModelAdmin):
    list_display = ("entry", "actor", "action", "created_at")
    list_filter = ("created_at",)
    search_fields = ("entry__patient_name", "action", "actor__username")
    readonly_fields = ("entry", "actor", "action", "created_at")
