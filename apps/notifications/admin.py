from django.contrib import admin

from .models import (
    NotificationBrowserClient,
    NotificationDeviceToken,
    NotificationEvent,
    NotificationPreference,
    NotificationRecipient,
)


class NotificationRecipientInline(admin.TabularInline):
    model = NotificationRecipient
    extra = 0
    readonly_fields = ("user", "state", "delivered_at", "seen_at", "read_at", "dismissed_at", "created_at")
    can_delete = False


@admin.register(NotificationEvent)
class NotificationEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "title", "source_app", "source_object_type", "source_object_id", "severity", "created_at")
    list_filter = ("source_app", "event_type", "severity", "created_at")
    search_fields = ("title", "body", "source_object_id", "event_id")
    readonly_fields = ("event_id", "created_at")
    inlines = [NotificationRecipientInline]


@admin.register(NotificationRecipient)
class NotificationRecipientAdmin(admin.ModelAdmin):
    list_display = ("event", "user", "state", "created_at", "seen_at", "read_at", "dismissed_at")
    list_filter = ("state", "created_at")
    search_fields = ("event__title", "user__username", "user__first_name", "user__last_name")
    readonly_fields = ("created_at",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "channel", "event_type", "enabled", "min_severity", "updated_at")
    list_filter = ("channel", "enabled", "min_severity")
    search_fields = ("user__username", "event_type")


@admin.register(NotificationBrowserClient)
class NotificationBrowserClientAdmin(admin.ModelAdmin):
    list_display = ("user", "user_agent_family", "notification_permission", "enabled", "last_seen_at")
    list_filter = ("notification_permission", "enabled", "user_agent_family")
    search_fields = ("user__username", "user_agent_family")
    readonly_fields = ("browser_fingerprint_hash", "created_at", "last_seen_at")


@admin.register(NotificationDeviceToken)
class NotificationDeviceTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "device_name", "platform", "is_active", "last_seen_at", "created_at")
    list_filter = ("platform", "revoked_at")
    search_fields = ("user__username", "device_name")
    readonly_fields = ("token_hash", "created_at", "last_seen_at", "revoked_at")
