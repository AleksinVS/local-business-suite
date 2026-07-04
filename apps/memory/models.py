import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class MemorySource(models.Model):
    class Status(models.TextChoices):
        ENABLED = "enabled", "Включен"
        DISABLED = "disabled", "Отключен"
        MISSING_ADAPTER = "missing_adapter", "Нет адаптера"
        ERROR = "error", "Ошибка"

    class TrustStatus(models.TextChoices):
        TRUSTED = "trusted", "Доверенный"
        REVIEW_REQUIRED = "review_required", "Требует ревью"
        CANDIDATE_ONLY = "candidate_only", "Только кандидат"
        QUARANTINED = "quarantined", "Карантин"
        BLOCKED = "blocked", "Заблокирован"

    class AuthorityClass(models.TextChoices):
        SYSTEM_OF_RECORD = "system_of_record", "Система-источник истины"
        APPROVED_CORPUS = "approved_corpus", "Утвержденный корпус"
        APPROVED_USER_MEMORY = "approved_user_memory", "Утвержденная пользовательская память"
        REVIEWED_ORG_KNOWLEDGE = "reviewed_org_knowledge", "Проверенное организационное знание"
        EXTERNAL_OBSERVATION = "external_observation", "Внешнее наблюдение"
        CANDIDATE_INPUT = "candidate_input", "Кандидатский ввод"

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
        verbose_name = "Источник памяти"
        verbose_name_plural = "Источники памяти"

    def __str__(self):
        return self.code


class MemorySourceObject(models.Model):
    class DiscoveryStatus(models.TextChoices):
        SEEN = "seen", "Найден"
        MISSING = "missing", "Отсутствует"
        CHANGED = "changed", "Изменен"
        ERROR = "error", "Ошибка"

    class IngestionStatus(models.TextChoices):
        PENDING = "pending", "Ожидает"
        READY = "ready", "Готов"
        INGESTED = "ingested", "Загружен"
        PARTIAL = "partial", "Частично"
        SKIPPED = "skipped", "Пропущен"
        FAILED = "failed", "Ошибка"

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
        verbose_name = "Объект источника памяти"
        verbose_name_plural = "Объекты источников памяти"

    def __str__(self):
        return f"{self.source.code}:{self.relative_path}"


class MemorySearchDocument(models.Model):
    class CorpusType(models.TextChoices):
        KNOWLEDGE = "knowledge", "Знания"
        SOURCE_DATA = "source_data", "Исходные данные"

    class ObjectKind(models.TextChoices):
        KNOWLEDGE_ITEM = "knowledge_item", "Элемент знания"
        SOURCE_OBJECT = "source_object", "Объект источника"
        SUMMARY = "summary", "Сводка"
        ANALYTICS_SLICE = "analytics_slice", "Аналитический срез"

    class IndexStatus(models.TextChoices):
        PENDING = "indexing_pending", "Ожидает индексации"
        READY = "ready", "Готов"
        DELETED = "deleted", "Удален"
        FAILED = "failed", "Ошибка"

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
        verbose_name = "Поисковый документ памяти"
        verbose_name_plural = "Поисковые документы памяти"

    def __str__(self):
        return self.document_id


class MemoryFullTextIndex(models.Model):
    """Database-backed full-text index row for production PostgreSQL search."""

    document_id = models.CharField(max_length=180, unique=True)
    search_text = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    scope_tokens = models.JSONField(default=list, blank=True)
    sensitivity = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)
    backend_schema_version = models.CharField(max_length=64, default="postgres-fts-v1")
    indexed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document_id"]
        indexes = [
            models.Index(fields=["document_id"]),
            models.Index(fields=["is_active", "sensitivity"]),
            models.Index(fields=["indexed_at"]),
        ]
        verbose_name = "Полнотекстовый индекс памяти"
        verbose_name_plural = "Полнотекстовые индексы памяти"

    def __str__(self):
        return self.document_id


class MemoryIngestionRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        RUNNING = "running", "Выполняется"
        SUCCEEDED = "succeeded", "Успешно"
        FAILED = "failed", "Ошибка"
        CANCELLED = "cancelled", "Отменено"

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
        verbose_name = "Запуск загрузки памяти"
        verbose_name_plural = "Запуски загрузки памяти"

    def __str__(self):
        return f"{self.source.code}:{self.status}:{self.pk}"


class MemoryIngestionIssue(models.Model):
    class IssueKind(models.TextChoices):
        ENCRYPTED_FILE = "encrypted_file", "Зашифрованный файл"
        UNSUPPORTED_FORMAT = "unsupported_format", "Неподдерживаемый формат"
        FILE_TOO_LARGE = "file_too_large", "Файл слишком большой"
        PARTIAL_INDEXED = "partial_indexed", "Частично проиндексировано"
        PARSER_TIMEOUT = "parser_timeout", "Тайм-аут парсера"
        OCR_TIMEOUT = "ocr_timeout", "Тайм-аут OCR"
        PII_BLOCKED = "pii_blocked", "Персональные данные заблокированы"
        PII_AUDIT = "pii_audit", "Аудит персональных данных"
        SECRET_BLOCKED = "secret_blocked", "Секрет заблокирован"
        ACL_UNRESOLVED = "acl_unresolved", "ACL не разрешен"
        SCHEMA_UNKNOWN_TYPE = "schema_unknown_type", "Неизвестный тип схемы"
        SCHEMA_UNKNOWN_RELATION = "schema_unknown_relation", "Неизвестная связь схемы"
        CANONICALIZATION_CONFLICT = "canonicalization_conflict", "Конфликт каноникализации"
        INDEX_FAILED = "index_failed", "Ошибка индекса"
        INDEX_STALE = "index_stale", "Индекс устарел"
        FTS_MISSING = "fts_missing", "Нет FTS"
        VECTOR_MISSING = "vector_missing", "Нет вектора"
        SOURCE_DELETED_INDEX_LEFT = "source_deleted_index_left", "Источник удален, индекс остался"

    class Status(models.TextChoices):
        OPEN = "open", "Открыта"
        ACKNOWLEDGED = "acknowledged", "Принята к сведению"
        NEEDS_EXPERT_REVIEW = "needs_expert_review", "Нужен эксперт"
        RESOLVED = "resolved", "Закрыта"
        IGNORED = "ignored", "Игнорируется"

    class Severity(models.TextChoices):
        INFO = "info", "Информация"
        WARNING = "warning", "Предупреждение"
        ERROR = "error", "Ошибка"
        BLOCKER = "blocker", "Блокер"

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
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_memory_ingestion_issues",
        blank=True,
        null=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_memory_ingestion_issues",
        blank=True,
        null=True,
    )
    resolution_code = models.CharField(max_length=80, blank=True)
    resolution_note = models.TextField(blank=True)
    review_due_at = models.DateTimeField(blank=True, null=True)
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
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["review_due_at"]),
        ]
        # ADR-0030 decision 4: MemoryReviewAction (the operator action-log
        # table) is removed; these review capability permissions move here,
        # to the issue queue that remains the operator's review home, so
        # existing capability checks (``has_memory_review_capability``) keep
        # working against ``memory.<codename>`` permission strings.
        permissions = [
            ("view_review_queue", "Может просматривать очередь ревью памяти"),
            ("review_issues", "Может ревьюировать проблемы памяти"),
            ("review_privacy_issues", "Может ревьюировать проблемы приватности памяти"),
            ("manage_search_index", "Может управлять поисковым индексом памяти"),
            ("view_memory_access_audit", "Может просматривать аудит доступа к памяти"),
        ]
        verbose_name = "Проблема загрузки памяти"
        verbose_name_plural = "Проблемы загрузки памяти"

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
        verbose_name = "Сущность графа памяти"
        verbose_name_plural = "Сущности графа памяти"

    def __str__(self):
        return self.entity_id


class MemoryGraphExtractionRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        RUNNING = "running", "Выполняется"
        SUCCEEDED = "succeeded", "Успешно"
        FAILED = "failed", "Ошибка"

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
        verbose_name = "Запуск извлечения графа памяти"
        verbose_name_plural = "Запуски извлечения графа памяти"

    def __str__(self):
        return f"{self.source.code}:{self.status}:{self.pk}"


class MemoryGraphSchemaProposal(models.Model):
    class ProposalKind(models.TextChoices):
        ENTITY_TYPE = "entity_type", "Тип сущности"
        RELATION_TYPE = "relation_type", "Тип связи"
        ATTRIBUTE_TYPE = "attribute_type", "Тип атрибута"
        CANONICALIZATION_RULE = "canonicalization_rule", "Правило каноникализации"
        FORBIDDEN_PATTERN = "forbidden_pattern", "Запрещенный паттерн"

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Предложено"
        NEEDS_EXPERT_REVIEW = "needs_expert_review", "Нужен эксперт"
        EXPERT_APPROVED = "expert_approved", "Одобрено экспертом"
        ACCEPTED = "accepted", "Принято"
        REJECTED = "rejected", "Отклонено"
        SUPERSEDED = "superseded", "Заменено"

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
        verbose_name = "Предложение схемы графа памяти"
        verbose_name_plural = "Предложения схемы графа памяти"

    def __str__(self):
        return f"{self.proposal_kind}:{self.status}:{self.pk}"


class MemoryGraphReviewItem(models.Model):
    class ItemKind(models.TextChoices):
        UNKNOWN_TYPE = "unknown_type", "Неизвестный тип"
        UNKNOWN_RELATION = "unknown_relation", "Неизвестная связь"
        LOW_CONFIDENCE = "low_confidence", "Низкая уверенность"
        CANONICALIZATION_CONFLICT = "canonicalization_conflict", "Конфликт каноникализации"
        DLP_WARNING = "dlp_warning", "Предупреждение DLP"

    class Status(models.TextChoices):
        OPEN = "open", "Открыт"
        NEEDS_EXPERT_REVIEW = "needs_expert_review", "Нужен эксперт"
        RESOLVED = "resolved", "Закрыт"
        REJECTED = "rejected", "Отклонен"

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
        verbose_name = "Элемент ревью графа памяти"
        verbose_name_plural = "Элементы ревью графа памяти"

    def __str__(self):
        return f"{self.item_kind}:{self.status}:{self.pk}"


class MemoryKnowledgeItem(models.Model):
    class Scope(models.TextChoices):
        PERSONAL = "personal", "Личное"
        ORGANIZATION = "organization", "Организационное"

    class Kind(models.TextChoices):
        FACT = "fact", "Факт"
        PREFERENCE = "preference", "Предпочтение"
        PROCEDURE = "procedure", "Процедура"
        DECISION = "decision", "Решение"
        SECRET_REFERENCE = "secret_reference", "Ссылка на секрет"

    class Status(models.TextChoices):
        ACTIVE = "active", "Активно"
        DELETED = "deleted", "Удалено"
        SUPERSEDED = "superseded", "Заменено"
        QUARANTINED = "quarantined", "Карантин"

    memory_id = models.CharField(max_length=160, unique=True)
    scope = models.CharField(max_length=32, choices=Scope.choices)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_knowledge_items",
        blank=True,
        null=True,
    )
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.FACT)
    text_hash = models.CharField(max_length=128)
    sensitivity = models.CharField(max_length=32, default="internal")
    scope_tokens = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    source_session = models.ForeignKey(
        "ai.ChatSession",
        on_delete=models.SET_NULL,
        related_name="memory_knowledge_items",
        blank=True,
        null=True,
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
        verbose_name = "Элемент знания памяти"
        verbose_name_plural = "Элементы знаний памяти"

    def __str__(self):
        return self.memory_id


class SecretHandle(models.Model):
    class Provider(models.TextChoices):
        EXTERNAL_VAULT_LINK = "external_vault_link", "Ссылка на внешнее хранилище"
        DISABLED = "disabled", "Отключено"
        LOCAL_STUB = "local_stub", "Локальная заглушка"
        OPENBAO = "openbao", "OpenBao"

    class Status(models.TextChoices):
        ACTIVE = "active", "Активен"
        REVOKED = "revoked", "Отозван"
        UNAVAILABLE = "unavailable", "Недоступен"

    handle = models.CharField(max_length=160, unique=True)
    provider = models.CharField(max_length=64, choices=Provider.choices, default=Provider.EXTERNAL_VAULT_LINK)
    label = models.CharField(max_length=255)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="secret_handles",
        blank=True,
        null=True,
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
        verbose_name = "Ссылка на секрет"
        verbose_name_plural = "Ссылки на секреты"

    def __str__(self):
        return self.handle


class SecretAccessAudit(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Создание"
        LINK = "link", "Связь"
        ROTATE = "rotate", "Ротация"
        REVOKE = "revoke", "Отзыв"
        SERVICE_RESOLVE = "service_resolve", "Сервисное разрешение"

    class Decision(models.TextChoices):
        ALLOWED = "allowed", "Разрешено"
        DENIED = "denied", "Запрещено"
        FAILED = "failed", "Ошибка"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="secret_access_audits",
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
        verbose_name = "Аудит доступа к секрету"
        verbose_name_plural = "Аудит доступа к секретам"

    def __str__(self):
        return f"{self.secret_handle_id}:{self.action}:{self.decision}"


class MemoryExternalConnectorJob(models.Model):
    """Database-backed external connector queue job."""

    job_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source_code = models.CharField(max_length=120, blank=True)
    job_kind = models.CharField(max_length=80)
    status = models.CharField(max_length=32)
    priority = models.IntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    next_attempt_at = models.DateTimeField(blank=True, null=True)
    locked_until = models.DateTimeField(blank=True, null=True)
    locked_by = models.CharField(max_length=120, blank=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    request_id = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "created_at", "job_id"]
        indexes = [
            models.Index(fields=["status", "next_attempt_at", "locked_until", "-priority", "created_at"]),
            models.Index(fields=["source_code", "status", "created_at"]),
            models.Index(fields=["job_kind", "status", "created_at"]),
            models.Index(fields=["idempotency_key"]),
            models.Index(fields=["job_id"]),
        ]
        verbose_name = "Задание очереди памяти"
        verbose_name_plural = "Задания очереди памяти"

    def __str__(self):
        return f"{self.status}:{self.job_id}"


class MemoryAccessAudit(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_access_audits",
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
        verbose_name = "Аудит доступа к памяти"
        verbose_name_plural = "Аудит доступа к памяти"

    def __str__(self):
        return f"{self.request_id}:{self.policy_decision}"


class MemoryEvalCase(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активен"
        DISABLED = "disabled", "Отключен"

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
        verbose_name = "Тестовый кейс памяти"
        verbose_name_plural = "Тестовые кейсы памяти"

    def __str__(self):
        return self.code
