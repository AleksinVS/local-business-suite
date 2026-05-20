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


class MemorySourceObject(models.Model):
    class DiscoveryStatus(models.TextChoices):
        SEEN = "seen", "Seen"
        MISSING = "missing", "Missing"
        CHANGED = "changed", "Changed"
        ERROR = "error", "Error"

    class IngestionStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        INGESTED = "ingested", "Ingested"
        PARTIAL = "partial", "Partial"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="source_objects")
    object_id = models.CharField(max_length=255)
    object_uri = models.CharField(max_length=1000)
    relative_path = models.CharField(max_length=1000)
    file_name = models.CharField(max_length=255)
    extension = models.CharField(max_length=32, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    mtime = models.DateTimeField(blank=True, null=True)
    content_hash = models.CharField(max_length=128, blank=True)
    etag_or_inode = models.CharField(max_length=255, blank=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)
    last_stable_at = models.DateTimeField(blank=True, null=True)
    discovery_status = models.CharField(max_length=16, choices=DiscoveryStatus.choices, default=DiscoveryStatus.SEEN)
    ingestion_status = models.CharField(max_length=16, choices=IngestionStatus.choices, default=IngestionStatus.PENDING)
    last_ingested_at = models.DateTimeField(blank=True, null=True)
    failure_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    partial_reason = models.TextField(blank=True)
    acl_fingerprint = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["source__code", "relative_path"]
        indexes = [
            models.Index(fields=["source", "object_id"]),
            models.Index(fields=["source", "relative_path"]),
            models.Index(fields=["content_hash"]),
            models.Index(fields=["discovery_status"]),
            models.Index(fields=["ingestion_status"]),
            models.Index(fields=["last_seen_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["source", "object_id"], name="memory_source_object_source_object_uniq"),
        ]
        verbose_name = "Memory source object"
        verbose_name_plural = "Memory source objects"

    def __str__(self):
        return f"{self.source.code}:{self.relative_path}"


class MemoryIngestionRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="ingestion_runs")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    dry_run = models.BooleanField(default=False)
    metrics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_ingestion_runs",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["source", "-created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["dry_run"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(started_at__isnull=True) | Q(started_at__lte=models.F("finished_at")),
                name="memory_ingestion_run_time_range",
            ),
        ]
        verbose_name = "Memory ingestion run"
        verbose_name_plural = "Memory ingestion runs"

    def __str__(self):
        return f"{self.source.code}:{self.status}:{self.pk}"


class MemoryIngestionIssue(models.Model):
    class IssueKind(models.TextChoices):
        ENCRYPTED_FILE = "encrypted_file", "Encrypted file"
        UNSUPPORTED_FORMAT = "unsupported_format", "Unsupported format"
        FILE_TOO_LARGE = "file_too_large", "File too large"
        PARTIAL_INDEXED = "partial_indexed", "Partial indexed"
        PARSER_TIMEOUT = "parser_timeout", "Parser timeout"
        OCR_TIMEOUT = "ocr_timeout", "OCR timeout"
        PII_BLOCKED = "pii_blocked", "PII blocked"
        SECRET_BLOCKED = "secret_blocked", "Secret blocked"
        ACL_UNRESOLVED = "acl_unresolved", "ACL unresolved"
        SCHEMA_UNKNOWN_TYPE = "schema_unknown_type", "Schema unknown type"
        SCHEMA_UNKNOWN_RELATION = "schema_unknown_relation", "Schema unknown relation"
        CANONICALIZATION_CONFLICT = "canonicalization_conflict", "Canonicalization conflict"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        NEEDS_EXPERT_REVIEW = "needs_expert_review", "Needs expert review"
        RESOLVED = "resolved", "Resolved"
        IGNORED = "ignored", "Ignored"

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        BLOCKER = "blocker", "Blocker"

    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="ingestion_issues")
    source_object = models.ForeignKey(
        MemorySourceObject,
        on_delete=models.PROTECT,
        related_name="ingestion_issues",
        blank=True,
        null=True,
    )
    run = models.ForeignKey(
        MemoryIngestionRun,
        on_delete=models.PROTECT,
        related_name="issues",
        blank=True,
        null=True,
    )
    issue_kind = models.CharField(max_length=64, choices=IssueKind.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.WARNING)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["source", "status"]),
            models.Index(fields=["issue_kind"]),
            models.Index(fields=["severity"]),
            models.Index(fields=["created_at"]),
        ]
        verbose_name = "Memory ingestion issue"
        verbose_name_plural = "Memory ingestion issues"

    def __str__(self):
        return f"{self.issue_kind}:{self.status}:{self.pk}"


class MemoryGraphEntity(models.Model):
    entity_id = models.CharField(max_length=160, unique=True)
    entity_type = models.CharField(max_length=80)
    canonical_name = models.CharField(max_length=255)
    aliases = models.JSONField(default=list, blank=True)
    attributes = models.JSONField(default=dict, blank=True)
    scope_tokens = models.JSONField(default=list, blank=True)
    sensitivity = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entity_type", "canonical_name"]
        indexes = [
            models.Index(fields=["entity_type"]),
            models.Index(fields=["canonical_name"]),
            models.Index(fields=["sensitivity"]),
            models.Index(fields=["is_active"]),
        ]
        verbose_name = "Memory graph entity"
        verbose_name_plural = "Memory graph entities"

    def __str__(self):
        return self.entity_id


class MemoryGraphExtractionRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="graph_extraction_runs")
    snapshot = models.ForeignKey(
        MemorySnapshot,
        on_delete=models.PROTECT,
        related_name="graph_extraction_runs",
        blank=True,
        null=True,
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    metrics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["source", "-created_at"]),
            models.Index(fields=["snapshot"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(started_at__isnull=True) | Q(started_at__lte=models.F("finished_at")),
                name="memory_graph_extraction_run_time_range",
            ),
        ]
        verbose_name = "Memory graph extraction run"
        verbose_name_plural = "Memory graph extraction runs"

    def __str__(self):
        return f"{self.source.code}:{self.status}:{self.pk}"


class MemoryGraphSchemaProposal(models.Model):
    class ProposalKind(models.TextChoices):
        ENTITY_TYPE = "entity_type", "Entity type"
        RELATION_TYPE = "relation_type", "Relation type"
        ATTRIBUTE_TYPE = "attribute_type", "Attribute type"
        CANONICALIZATION_RULE = "canonicalization_rule", "Canonicalization rule"
        FORBIDDEN_PATTERN = "forbidden_pattern", "Forbidden pattern"

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        NEEDS_EXPERT_REVIEW = "needs_expert_review", "Needs expert review"
        EXPERT_APPROVED = "expert_approved", "Expert approved"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        SUPERSEDED = "superseded", "Superseded"

    proposal_kind = models.CharField(max_length=64, choices=ProposalKind.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PROPOSED)
    department = models.CharField(max_length=120, blank=True)
    payload = models.JSONField(default=dict)
    evidence = models.JSONField(default=list, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    rationale = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_graph_schema_reviews",
        blank=True,
        null=True,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["proposal_kind"]),
            models.Index(fields=["status"]),
            models.Index(fields=["department"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(confidence__gte=0) & Q(confidence__lte=1),
                name="memory_graph_schema_proposal_confidence_0_1",
            ),
        ]
        verbose_name = "Memory graph schema proposal"
        verbose_name_plural = "Memory graph schema proposals"

    def __str__(self):
        return f"{self.proposal_kind}:{self.status}:{self.pk}"


class MemoryGraphReviewItem(models.Model):
    class ItemKind(models.TextChoices):
        UNKNOWN_TYPE = "unknown_type", "Unknown type"
        UNKNOWN_RELATION = "unknown_relation", "Unknown relation"
        LOW_CONFIDENCE = "low_confidence", "Low confidence"
        CANONICALIZATION_CONFLICT = "canonicalization_conflict", "Canonicalization conflict"
        DLP_WARNING = "dlp_warning", "DLP warning"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        NEEDS_EXPERT_REVIEW = "needs_expert_review", "Needs expert review"
        RESOLVED = "resolved", "Resolved"
        REJECTED = "rejected", "Rejected"

    item_kind = models.CharField(max_length=64, choices=ItemKind.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="graph_review_items", blank=True, null=True)
    snapshot = models.ForeignKey(MemorySnapshot, on_delete=models.PROTECT, related_name="graph_review_items", blank=True, null=True)
    payload = models.JSONField(default=dict)
    evidence = models.JSONField(default=list, blank=True)
    decision = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_graph_review_items",
        blank=True,
        null=True,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["item_kind"]),
            models.Index(fields=["status"]),
            models.Index(fields=["source", "status"]),
        ]
        verbose_name = "Memory graph review item"
        verbose_name_plural = "Memory graph review items"

    def __str__(self):
        return f"{self.item_kind}:{self.status}:{self.pk}"


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
