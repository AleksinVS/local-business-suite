from django.conf import settings
from django.db import models
from django.db.models import Q


class MemorySource(models.Model):
    class Status(models.TextChoices):
        ENABLED = "enabled", "Enabled"
        DISABLED = "disabled", "Disabled"
        ERROR = "error", "Error"

    code = models.CharField(max_length=120, unique=True)
    title = models.CharField(max_length=255)
    source_kind = models.CharField(max_length=64)
    domain = models.CharField(max_length=64)
    owner = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ENABLED)
    sync_mode = models.CharField(max_length=32, blank=True)
    scope_rule = models.CharField(max_length=120, blank=True)
    sensitivity = models.CharField(max_length=32)
    pii_policy = models.CharField(max_length=120, blank=True)
    extractor_profile = models.CharField(max_length=120, blank=True)
    chunking_profile = models.CharField(max_length=120, blank=True)
    index_profiles = models.JSONField(default=list, blank=True)
    config = models.JSONField(default=dict, blank=True)
    watermarks = models.JSONField(default=dict, blank=True)
    last_discovered_at = models.DateTimeField(blank=True, null=True)
    last_synced_at = models.DateTimeField(blank=True, null=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["domain"]),
            models.Index(fields=["source_kind"]),
            models.Index(fields=["sensitivity"]),
        ]
        verbose_name = "Memory source"
        verbose_name_plural = "Memory sources"

    def __str__(self):
        return self.code


class MemorySnapshot(models.Model):
    class Status(models.TextChoices):
        READY = "ready", "Ready"
        BLOCKED = "blocked", "Blocked"
        FAILED = "failed", "Failed"

    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="snapshots")
    source_object_id = models.CharField(max_length=255)
    content_hash = models.CharField(max_length=128)
    schema_version = models.CharField(max_length=64)
    extractor_version = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    extracted_at = models.DateTimeField()
    valid_from = models.DateTimeField(blank=True, null=True)
    valid_to = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    raw_path = models.CharField(max_length=500)
    safe_path = models.CharField(max_length=500, blank=True)
    pii_policy_applied = models.CharField(max_length=120, blank=True)
    scope_tokens = models.JSONField(default=list, blank=True)
    sensitivity = models.CharField(max_length=32)
    blocked_reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-extracted_at", "-id"]
        indexes = [
            models.Index(fields=["source", "source_object_id"]),
            models.Index(fields=["content_hash"]),
            models.Index(fields=["status"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["sensitivity"]),
            models.Index(fields=["-extracted_at", "-id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_object_id", "content_hash"],
                name="memory_snapshot_source_obj_hash_uniq",
            ),
            models.UniqueConstraint(
                fields=["source", "source_object_id"],
                condition=Q(is_active=True),
                name="memory_one_active_snapshot_per_obj",
            ),
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_from__isnull=True) | Q(valid_from__lte=models.F("valid_to")),
                name="memory_snapshot_valid_range",
            ),
        ]
        verbose_name = "Memory snapshot"
        verbose_name_plural = "Memory snapshots"

    def __str__(self):
        return f"{self.source.code}:{self.source_object_id}@{self.content_hash[:12]}"


class MemoryChunk(models.Model):
    snapshot = models.ForeignKey(MemorySnapshot, on_delete=models.PROTECT, related_name="chunks")
    chunk_id = models.CharField(max_length=160, unique=True)
    source_code = models.CharField(max_length=120)
    source_object_id = models.CharField(max_length=255)
    snapshot_hash = models.CharField(max_length=128)
    position = models.PositiveIntegerField(default=0)
    text_path = models.CharField(max_length=500, blank=True)
    text_hash = models.CharField(max_length=128)
    metadata = models.JSONField(default=dict, blank=True)
    scope_tokens = models.JSONField(default=list, blank=True)
    sensitivity = models.CharField(max_length=32)
    valid_from = models.DateTimeField(blank=True, null=True)
    valid_to = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["snapshot_id", "position", "id"]
        indexes = [
            models.Index(fields=["source_code", "source_object_id"]),
            models.Index(fields=["snapshot_hash"]),
            models.Index(fields=["text_hash"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["sensitivity"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "position"],
                name="memory_chunk_snapshot_position_uniq",
            ),
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_from__isnull=True) | Q(valid_from__lte=models.F("valid_to")),
                name="memory_chunk_valid_range",
            ),
        ]
        verbose_name = "Memory chunk"
        verbose_name_plural = "Memory chunks"

    def __str__(self):
        return self.chunk_id


class MemoryGraphFact(models.Model):
    fact_id = models.CharField(max_length=160, unique=True)
    source_chunk = models.ForeignKey(MemoryChunk, on_delete=models.PROTECT, related_name="graph_facts")
    snapshot = models.ForeignKey(MemorySnapshot, on_delete=models.PROTECT, related_name="graph_facts")
    snapshot_hash = models.CharField(max_length=128)
    subject_id = models.CharField(max_length=160)
    predicate = models.CharField(max_length=80)
    object_id = models.CharField(max_length=160)
    subject_type = models.CharField(max_length=80, blank=True)
    object_type = models.CharField(max_length=80, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    extracted_by = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    scope_tokens = models.JSONField(default=list, blank=True)
    sensitivity = models.CharField(max_length=32)
    valid_from = models.DateTimeField(blank=True, null=True)
    valid_to = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fact_id"]
        indexes = [
            models.Index(fields=["subject_id"]),
            models.Index(fields=["predicate"]),
            models.Index(fields=["object_id"]),
            models.Index(fields=["snapshot_hash"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["sensitivity"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(confidence__gte=0) & Q(confidence__lte=1),
                name="memory_graph_fact_confidence_0_1",
            ),
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_from__isnull=True) | Q(valid_from__lte=models.F("valid_to")),
                name="memory_graph_fact_valid_range",
            ),
        ]
        verbose_name = "Memory graph fact"
        verbose_name_plural = "Memory graph facts"

    def __str__(self):
        return self.fact_id


class MemoryIndexJob(models.Model):
    class JobKind(models.TextChoices):
        DISCOVER = "discover", "Discover"
        SYNC = "sync", "Sync"
        REINDEX = "reindex", "Reindex"
        EVAL = "eval", "Eval"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="index_jobs", blank=True, null=True)
    job_kind = models.CharField(max_length=16, choices=JobKind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    request_id = models.CharField(max_length=120, blank=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    error_message = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_index_jobs",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["job_kind"]),
            models.Index(fields=["status"]),
            models.Index(fields=["request_id"]),
            models.Index(fields=["-created_at", "-id"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(started_at__isnull=True) | Q(started_at__lte=models.F("finished_at")),
                name="memory_index_job_time_range",
            ),
            models.CheckConstraint(
                condition=Q(attempts__lte=models.F("max_attempts")),
                name="memory_index_job_attempts_lte_max",
            ),
        ]
        verbose_name = "Memory index job"
        verbose_name_plural = "Memory index jobs"

    def __str__(self):
        return f"{self.job_kind}:{self.status}:{self.pk}"


class MemoryAccessAudit(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memory_access_audits")
    request_id = models.CharField(max_length=120)
    query_hash = models.CharField(max_length=128, blank=True)
    tool_name = models.CharField(max_length=120, default="memory.search")
    allowed_scope_tokens = models.JSONField(default=list, blank=True)
    returned_chunk_ids = models.JSONField(default=list, blank=True)
    returned_fact_ids = models.JSONField(default=list, blank=True)
    denied_reason = models.TextField(blank=True)
    policy_decision = models.CharField(max_length=32)
    retrieval_trace = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["request_id"]),
            models.Index(fields=["policy_decision"]),
            models.Index(fields=["tool_name"]),
        ]
        verbose_name = "Memory access audit"
        verbose_name_plural = "Memory access audits"

    def __str__(self):
        return f"{self.request_id}:{self.policy_decision}"


class MemoryEvalCase(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"

    code = models.CharField(max_length=120, unique=True)
    title = models.CharField(max_length=255)
    suite = models.CharField(max_length=120, default="smoke")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    question = models.TextField()
    expected_source_codes = models.JSONField(default=list, blank=True)
    expected_chunk_ids = models.JSONField(default=list, blank=True)
    forbidden_source_codes = models.JSONField(default=list, blank=True)
    forbidden_scope_tokens = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["suite", "code"]
        indexes = [
            models.Index(fields=["suite"]),
            models.Index(fields=["status"]),
        ]
        verbose_name = "Memory eval case"
        verbose_name_plural = "Memory eval cases"

    def __str__(self):
        return self.code
