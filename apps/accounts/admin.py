from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group

from .models import ExternalIdentity, GroupProfile, User


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


class GroupProfileInline(admin.StackedInline):
    model = GroupProfile
    can_delete = False
    fields = ("title", "description", "is_predefined")


admin.site.unregister(Group)


@admin.register(Group)
class GroupAdminWithProfile(GroupAdmin):
    inlines = [GroupProfileInline]
    list_display = ("name", "profile_title", "profile_description_short")

    @admin.display(description="Название")
    def profile_title(self, obj):
        profile = getattr(obj, "profile", None)
        return getattr(profile, "title", "") or ""

    @admin.display(description="Комментарий")
    def profile_description_short(self, obj):
        profile = getattr(obj, "profile", None)
        description = getattr(profile, "description", "") or ""
        if len(description) > 80:
            return description[:80].rstrip() + "…"
        return description
