from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ExternalIdentity, User


class ExternalIdentityInline(admin.TabularInline):
    model = ExternalIdentity
    extra = 0
    readonly_fields = ("last_synced_at", "created_at", "updated_at")


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Организация", {"fields": ("department",)}),
    )
    list_display = ("username", "email", "first_name", "last_name", "department", "is_staff", "is_active")
    list_filter = UserAdmin.list_filter + ("department",)
    inlines = [ExternalIdentityInline]


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "domain", "username", "upn", "sync_status", "last_synced_at")
    list_filter = ("provider", "domain", "sync_status")
    search_fields = ("user__username", "username", "upn", "subject_id", "distinguished_name")
