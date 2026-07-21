from django.contrib import admin

from .models import MedicalDevice


@admin.register(MedicalDevice)
class MedicalDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "device_type",
        "manufacturer",
        "production_country",
        "department",
        "address",
        "serial_number",
        "inventory_number",
        "registration_certificate_number",
        "operational_status",
    )
    list_filter = (
        "department",
        "operational_status",
        "device_type",
        "manufacturer",
        "production_country",
        "is_archived",
    )
    search_fields = (
        "name",
        "device_type",
        "manufacturer",
        "production_country",
        "model",
        "serial_number",
        "inventory_number",
        "registration_certificate_number",
        "location",
        "address",
        "department__name",
    )
    fieldsets = (
        (None, {
            "fields": (
                "name",
                "device_type",
                "manufacturer",
                "production_country",
                "model",
                "serial_number",
                "inventory_number",
            )
        }),
        ("Регистрационные данные", {
            "fields": (
                "registration_date",
                "registration_certificate_number",
                "production_date",
                "service_life_years",
            )
        }),
        ("Размещение", {
            "fields": (
                "department",
                "address",
                "location",
            )
        }),
        ("Эксплуатация", {
            "fields": (
                "operational_status",
                "commissioned_at",
                "decommissioned_at",
                "decommission_reason",
                "notes",
            )
        }),
        ("Архив", {
            "fields": (
                "is_archived",
                "archived_at",
            )
        }),
    )