from django.contrib import admin

from .models import Department


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "oid", "parent")
    list_filter = ("parent",)
    search_fields = ("name", "oid", "parent__name")
