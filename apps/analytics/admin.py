from django.contrib import admin

from .models import (
    AnalyticsAccessAudit,
    AnalyticsCase,
    AnalyticsContentObject,
    AnalyticsDiagnosticRun,
    AnalyticsDuplicateCandidate,
    AnalyticsEvidenceRef,
    AnalyticsExtractionPacket,
    AnalyticsExtractionRun,
    AnalyticsFact,
    AnalyticsMetricCandidate,
    AnalyticsMetricSnapshot,
    AnalyticsSampleManifest,
    AnalyticsSignal,
    AnalyticsSource,
)


@admin.register(AnalyticsSource)
class AnalyticsSourceAdmin(admin.ModelAdmin):
    list_display = ("code", "source_kind", "status", "owner", "sensitivity", "last_synced_at")
    list_filter = ("source_kind", "status", "sensitivity")
    search_fields = ("code", "title", "owner")


@admin.register(AnalyticsContentObject)
class AnalyticsContentObjectAdmin(admin.ModelAdmin):
    list_display = ("source", "source_object_id", "content_kind", "business_key", "is_active")
    list_filter = ("content_kind", "is_active", "sensitivity")
    search_fields = ("source_object_id", "title", "business_key", "raw_sha256", "normalized_text_sha256")


@admin.register(AnalyticsFact)
class AnalyticsFactAdmin(admin.ModelAdmin):
    list_display = ("fact_id", "fact_type", "event_time", "sensitivity", "is_active")
    list_filter = ("fact_type", "sensitivity", "is_active")
    search_fields = ("fact_id", "semantic_hash")


@admin.register(AnalyticsSignal)
class AnalyticsSignalAdmin(admin.ModelAdmin):
    list_display = ("signal_id", "monitor_code", "severity", "status", "created_at")
    list_filter = ("status", "severity", "monitor_code")
    search_fields = ("signal_id", "message")


for model in (
    AnalyticsAccessAudit,
    AnalyticsCase,
    AnalyticsDiagnosticRun,
    AnalyticsDuplicateCandidate,
    AnalyticsEvidenceRef,
    AnalyticsExtractionPacket,
    AnalyticsExtractionRun,
    AnalyticsMetricCandidate,
    AnalyticsMetricSnapshot,
    AnalyticsSampleManifest,
):
    admin.site.register(model)
