from django.contrib import admin

from .models import MedicalDevice


@admin.register(MedicalDevice)
class MedicalDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "department",
        "location",
        "serial_number",
        "operational_status",
    )
    list_filter = ("department", "operational_status")
    search_fields = (
        "name",
        "manufacturer",
        "model",
        "serial_number",
        "inventory_number",
        "location",
    )
