import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class MemorySource(models.Model):
    class Status(models.TextChoices):
        ENABLED = "enabled", "Enabled"
        DISABLED = "disabled", "Disabled"
        ERROR = "error", "Error"

    class TrustStatus(models.TextChoices):
        TRUSTED = "trusted", "Trusted"
        REVIEW_REQUIRED = "review_required", "Review required"
        CANDIDATE_ONLY = "candidate_only", "Candidate only"
        QUARANTINED = "quarantined", "Quarantined"
        BLOCKED = "blocked", "Blocked"

    class AuthorityClass(models.TextChoices):
        SYSTEM_OF_RECORD = "system_of_record", "System of record"
        APPROVED_CORPUS = "approved_corpus", "Approved corpus"
        APPROVED_USER_MEMORY = "approved_user_memory", "Approved user memory"
        REVIEWED_ORG_KNOWLEDGE = "reviewed_org_knowledge", "Reviewed organization knowledge"
        EXTERNAL_OBSERVATION = "external_observation", "External observation"
        CANDIDATE_INPUT = "candidate_input", "Candidate input"

    code = models.CharField(max_length=120, unique=True)
    title = models.CharField(max_length=255)
    source_kind = models.CharField(max_length=64)
    domain = models.CharField(max_length=64)
    owner = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ENABLED)
    trust_status = models.CharField(max_length=32, choices=TrustStatus.choices, blank=True)
    authority_class = models.CharField(max_length=64, choices=AuthorityClass.choices, blank=True)
    trusted_for_context = models.BooleanField(default=False)
    requires_source_review = models.BooleanField(default=True)
    review_owner = models.CharField(max_length=120, blank=True)
    trusted_context_kinds = models.JSONField(default=list, blank=True)
    untrusted_handling = models.CharField(max_length=32, blank=True)
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
            models.Index(fields=["trust_status", "trusted_for_context"]),
            models.Index(fields=["authority_class"]),
        ]
        verbose_name = "Memory source"
        verbose_name_plural = "Memory sources"

    def __str__(self):
        return self.code


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


class MemorySearchDocument(models.Model):
    class CorpusType(models.TextChoices):
        KNOWLEDGE = "knowledge", "Knowledge"
        SOURCE_DATA = "source_data", "Source data"

    class ObjectKind(models.TextChoices):
        KNOWLEDGE_ITEM = "knowledge_item", "Knowledge item"
        SOURCE_OBJECT = "source_object", "Source object"
        SUMMARY = "summary", "Summary"
        ANALYTICS_SLICE = "analytics_slice", "Analytics slice"

    class IndexStatus(models.TextChoices):
        PENDING = "indexing_pending", "Indexing pending"
        READY = "ready", "Ready"
        DELETED = "deleted", "Deleted"
        FAILED = "failed", "Failed"

    document_id = models.CharField(max_length=180, unique=True)
    corpus_type = models.CharField(max_length=32, choices=CorpusType.choices)
    object_kind = models.CharField(max_length=64, choices=ObjectKind.choices)
    knowledge_item = models.ForeignKey(
        "memory.MemoryKnowledgeItem",
        on_delete=models.PROTECT,
        related_name="search_documents",
        blank=True,
        null=True,
    )
    source_object = models.ForeignKey(
        MemorySourceObject,
        on_delete=models.PROTECT,
        related_name="search_documents",
        blank=True,
        null=True,
    )
    body_hash = models.CharField(max_length=128, blank=True)
    index_status = models.CharField(max_length=32, choices=IndexStatus.choices, default=IndexStatus.PENDING)
    metadata = models.JSONField(default=dict, blank=True)
    indexed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["corpus_type", "document_id"]
        indexes = [
            models.Index(fields=["document_id"]),
            models.Index(fields=["corpus_type", "object_kind"]),
            models.Index(fields=["index_status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(corpus_type="knowledge", knowledge_item__isnull=False)
                | Q(corpus_type="source_data", source_object__isnull=False)
                | Q(object_kind__in=["summary", "analytics_slice"]),
                name="memory_search_document_target_present",
            ),
        ]
        verbose_name = "Memory search document"
        verbose_name_plural = "Memory search documents"

    def __str__(self):
        return self.document_id


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
        db_constraint=False,
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
        db_constraint=False,
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
    payload = models.JSONField(default=dict)
    evidence = models.JSONField(default=list, blank=True)
    decision = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_graph_review_items",
        blank=True,
        null=True,
        db_constraint=False,
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


class MemoryWriteRequest(models.Model):
    class TargetScope(models.TextChoices):
        PERSONAL = "personal", "Personal"
        ORGANIZATION = "organization", "Organization"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        ACCEPTED = "accepted", "Accepted"
        CANDIDATE_CREATED = "candidate_created", "Candidate created"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_write_requests",
        db_constraint=False,
    )
    session = models.ForeignKey(
        "ai.ChatSession",
        on_delete=models.PROTECT,
        related_name="memory_write_requests",
        blank=True,
        null=True,
        db_constraint=False,
    )
    message_ids = models.JSONField(default=list, blank=True)
    target_scope = models.CharField(max_length=32, choices=TargetScope.choices, default=TargetScope.PERSONAL)
    user_note = models.TextField(blank=True)
    importance = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.QUEUED)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["target_scope", "status"]),
            models.Index(fields=["status"]),
            models.Index(fields=["request_id"]),
        ]
        verbose_name = "Memory write request"
        verbose_name_plural = "Memory write requests"

    def __str__(self):
        return f"{self.request_id}:{self.target_scope}:{self.status}"


class MemoryKnowledgeItem(models.Model):
    class Scope(models.TextChoices):
        PERSONAL = "personal", "Personal"
        ORGANIZATION = "organization", "Organization"

    class Kind(models.TextChoices):
        FACT = "fact", "Fact"
        PREFERENCE = "preference", "Preference"
        PROCEDURE = "procedure", "Procedure"
        DECISION = "decision", "Decision"
        SECRET_REFERENCE = "secret_reference", "Secret reference"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DELETED = "deleted", "Deleted"
        SUPERSEDED = "superseded", "Superseded"
        QUARANTINED = "quarantined", "Quarantined"

    memory_id = models.CharField(max_length=160, unique=True)
    scope = models.CharField(max_length=32, choices=Scope.choices)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_knowledge_items",
        blank=True,
        null=True,
        db_constraint=False,
    )
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.FACT)
    text_hash = models.CharField(max_length=128)
    sensitivity = models.CharField(max_length=32, default="internal")
    scope_tokens = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    source_session = models.ForeignKey(
        "ai.ChatSession",
        on_delete=models.PROTECT,
        related_name="memory_knowledge_items",
        blank=True,
        null=True,
        db_constraint=False,
    )
    source_message_ids = models.JSONField(default=list, blank=True)
    source_content_hash = models.CharField(max_length=128, blank=True)
    source_refs = models.JSONField(default=list, blank=True)
    source_code = models.CharField(max_length=120, default="chat")
    source_kind = models.CharField(max_length=64, default="chat")
    knowledge_file_path = models.CharField(max_length=1000, blank=True)
    knowledge_file_hash = models.CharField(max_length=128, blank=True)
    knowledge_file_commit = models.CharField(max_length=80, blank=True)
    index_status = models.CharField(max_length=32, default="indexing_pending")
    provenance = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_memory_knowledge_items",
        db_constraint=False,
    )
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="superseded_by",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scope", "owner_user_id", "-updated_at", "-id"]
        indexes = [
            models.Index(fields=["scope", "status"]),
            models.Index(fields=["owner_user", "status"]),
            models.Index(fields=["text_hash"]),
            models.Index(fields=["sensitivity"]),
            models.Index(fields=["memory_id"]),
            models.Index(fields=["source_code", "source_kind"]),
            models.Index(fields=["index_status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(scope="personal", owner_user__isnull=False) | Q(scope="organization"),
                name="memory_knowledge_personal_has_owner",
            ),
        ]
        verbose_name = "Memory knowledge item"
        verbose_name_plural = "Memory knowledge items"

    def __str__(self):
        return self.memory_id


class MemoryKnowledgeEvent(models.Model):
    class EventType(models.TextChoices):
        REMEMBERED = "remembered", "Remembered"
        EDITED = "edited", "Edited"
        DELETED = "deleted", "Deleted"
        REFLECTED = "reflected", "Reflected"
        PROMOTED = "promoted", "Promoted"
        REJECTED = "rejected", "Rejected"
        SECRET_CAPTURED = "secret_captured", "Secret captured"

    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    knowledge_item = models.ForeignKey(
        MemoryKnowledgeItem,
        on_delete=models.PROTECT,
        related_name="events",
        blank=True,
        null=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_knowledge_events",
        db_constraint=False,
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["event_type"]),
            models.Index(fields=["actor", "created_at"]),
        ]
        verbose_name = "Memory knowledge event"
        verbose_name_plural = "Memory knowledge events"

    def __str__(self):
        return f"{self.event_type}:{self.event_id}"


class MemoryKnowledgeCandidate(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        NEEDS_REVIEW = "needs_review", "Needs review"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        MERGED = "merged", "Merged"
        SUPERSEDED = "superseded", "Superseded"

    source_item = models.ForeignKey(
        MemoryKnowledgeItem,
        on_delete=models.PROTECT,
        related_name="organization_candidates",
        blank=True,
        null=True,
    )
    proposed_text = models.TextField()
    proposed_payload = models.JSONField(default=dict, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PROPOSED)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_candidate_reviews",
        blank=True,
        null=True,
        db_constraint=False,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    decision = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_candidates",
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_by", "-created_at"]),
            models.Index(fields=["reviewer", "reviewed_at"]),
        ]
        verbose_name = "Memory knowledge candidate"
        verbose_name_plural = "Memory knowledge candidates"

    def __str__(self):
        return f"{self.status}:{self.pk}"


class MemoryReflectionRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    window_start = models.DateTimeField(blank=True, null=True)
    window_end = models.DateTimeField(blank=True, null=True)
    dry_run = models.BooleanField(default=False)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    metrics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_reflection_runs",
        blank=True,
        null=True,
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["dry_run"]),
            models.Index(fields=["window_start", "window_end"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(started_at__isnull=True) | Q(started_at__lte=models.F("finished_at")),
                name="memory_reflection_run_time_range",
            ),
        ]
        verbose_name = "Memory reflection run"
        verbose_name_plural = "Memory reflection runs"

    def __str__(self):
        return f"{self.status}:{self.pk}"


class SecretHandle(models.Model):
    class Provider(models.TextChoices):
        EXTERNAL_VAULT_LINK = "external_vault_link", "External vault link"
        DISABLED = "disabled", "Disabled"
        LOCAL_STUB = "local_stub", "Local stub"
        OPENBAO = "openbao", "OpenBao"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"
        UNAVAILABLE = "unavailable", "Unavailable"

    handle = models.CharField(max_length=160, unique=True)
    provider = models.CharField(max_length=64, choices=Provider.choices, default=Provider.EXTERNAL_VAULT_LINK)
    label = models.CharField(max_length=255)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="secret_handles",
        blank=True,
        null=True,
        db_constraint=False,
    )
    scope = models.CharField(max_length=32, blank=True)
    url = models.CharField(max_length=1000, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    sensitivity = models.CharField(max_length=32, default="secret")
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_secret_handles",
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["owner_user", "status"]),
            models.Index(fields=["handle"]),
        ]
        verbose_name = "Secret handle"
        verbose_name_plural = "Secret handles"

    def __str__(self):
        return self.handle


class SecretAccessAudit(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Create"
        LINK = "link", "Link"
        ROTATE = "rotate", "Rotate"
        REVOKE = "revoke", "Revoke"
        SERVICE_RESOLVE = "service_resolve", "Service resolve"

    class Decision(models.TextChoices):
        ALLOWED = "allowed", "Allowed"
        DENIED = "denied", "Denied"
        FAILED = "failed", "Failed"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="secret_access_audits",
        db_constraint=False,
    )
    secret_handle = models.ForeignKey(SecretHandle, on_delete=models.PROTECT, related_name="access_audits")
    action = models.CharField(max_length=32, choices=Action.choices)
    decision = models.CharField(max_length=32, choices=Decision.choices)
    request_id = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["secret_handle", "-created_at"]),
            models.Index(fields=["action", "decision"]),
            models.Index(fields=["request_id"]),
        ]
        verbose_name = "Secret access audit"
        verbose_name_plural = "Secret access audits"

    def __str__(self):
        return f"{self.secret_handle_id}:{self.action}:{self.decision}"


class MemoryIndexJob(models.Model):
    class JobKind(models.TextChoices):
        DISCOVER = "discover", "Discover"
        SYNC = "sync", "Sync"
        REINDEX = "reindex", "Reindex"
        EVAL = "eval", "Eval"
        REMEMBER = "remember", "Remember"
        REFLECT = "reflect", "Reflect"

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
        db_constraint=False,
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
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_access_audits",
        db_constraint=False,
    )
    request_id = models.CharField(max_length=120)
    query_hash = models.CharField(max_length=128, blank=True)
    tool_name = models.CharField(max_length=120, default="memory.search")
    allowed_scope_tokens = models.JSONField(default=list, blank=True)
    returned_document_ids = models.JSONField(default=list, blank=True)
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
    expected_document_ids = models.JSONField(default=list, blank=True)
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
