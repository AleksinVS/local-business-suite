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


class MemoryFileObject(models.Model):
    class LifecycleStatus(models.TextChoices):
        SOURCE_ACTIVE = "source_active", "Активен в источнике"
        MOVE_PLANNED = "move_planned", "Перенос запланирован"
        MANAGED_ACTIVE = "managed_active", "Активен в управляемом хранилище"
        SOURCE_QUARANTINED = "source_quarantined", "Исходник в карантине"
        SOURCE_PURGED = "source_purged", "Исходник удален"
        NEEDS_REVIEW = "needs_review", "Требует ревью"
        BLOCKED = "blocked", "Заблокирован"

    file_id = models.CharField(max_length=80, unique=True)
    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="file_objects")
    current_version = models.ForeignKey(
        "memory.MemoryFileObjectVersion",
        on_delete=models.SET_NULL,
        related_name="+",
        blank=True,
        null=True,
    )
    current_physical_placement = models.ForeignKey(
        "memory.MemoryFilePhysicalPlacement",
        on_delete=models.SET_NULL,
        related_name="+",
        blank=True,
        null=True,
    )
    lifecycle_status = models.CharField(
        max_length=32,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.SOURCE_ACTIVE,
    )
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["source__code", "file_id"]
        indexes = [
            models.Index(fields=["source", "lifecycle_status"]),
            models.Index(fields=["file_id"]),
            models.Index(fields=["last_seen_at"]),
        ]
        verbose_name = "Файл памяти"
        verbose_name_plural = "Файлы памяти"

    def __str__(self):
        return self.file_id


class MemoryFileObjectVersion(models.Model):
    class VersionStatus(models.TextChoices):
        CURRENT = "current", "Текущая"
        HISTORICAL = "historical", "Историческая"
        BLOCKED = "blocked", "Заблокирована"

    file_object = models.ForeignKey(MemoryFileObject, on_delete=models.PROTECT, related_name="versions")
    source_object = models.ForeignKey(
        MemorySourceObject,
        on_delete=models.PROTECT,
        related_name="file_versions",
        blank=True,
        null=True,
    )
    sha256 = models.CharField(max_length=128)
    size_bytes = models.PositiveBigIntegerField(default=0)
    mtime = models.DateTimeField(blank=True, null=True)
    storage_backend = models.CharField(max_length=32, default="source_fs")
    storage_ref = models.CharField(max_length=1200)
    version_status = models.CharField(max_length=32, choices=VersionStatus.choices, default=VersionStatus.CURRENT)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["file_object__file_id", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["sha256", "size_bytes"]),
            models.Index(fields=["storage_backend"]),
            models.Index(fields=["version_status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["file_object", "sha256", "size_bytes"],
                name="memory_file_version_file_hash_size_uniq",
            ),
        ]
        verbose_name = "Версия файла памяти"
        verbose_name_plural = "Версии файлов памяти"

    def __str__(self):
        return f"{self.file_object_id}:{self.sha256[:12]}"


class MemoryFilePhysicalPlacement(models.Model):
    class StorageBackend(models.TextChoices):
        SOURCE_FS = "source_fs", "Исходная файловая система"
        MANAGED_FS = "managed_fs", "Управляемая файловая система"
        S3_COMPATIBLE = "s3_compatible", "S3-совместимое хранилище"

    class PathRole(models.TextChoices):
        SOURCE_CURRENT = "source_current", "Текущий исходный путь"
        SOURCE_ALIAS = "source_alias", "Исторический исходный путь"
        MANAGED_CURRENT = "managed_current", "Текущий управляемый путь"
        QUARANTINE = "quarantine", "Карантин"
        PURGED = "purged", "Удалено"

    class PlacementStatus(models.TextChoices):
        ACTIVE = "active", "Активно"
        MIGRATED = "migrated", "Перенесено"
        QUARANTINED = "quarantined", "Карантин"
        PURGED = "purged", "Удалено"
        FAILED = "failed", "Ошибка"

    file_object = models.ForeignKey(MemoryFileObject, on_delete=models.PROTECT, related_name="physical_placements")
    source_object = models.ForeignKey(
        MemorySourceObject,
        on_delete=models.PROTECT,
        related_name="physical_placements",
        blank=True,
        null=True,
    )
    storage_backend = models.CharField(max_length=32, choices=StorageBackend.choices)
    physical_ref = models.CharField(max_length=1200)
    relative_path = models.CharField(max_length=1000, blank=True)
    path_role = models.CharField(max_length=32, choices=PathRole.choices)
    placement_status = models.CharField(max_length=32, choices=PlacementStatus.choices, default=PlacementStatus.ACTIVE)
    is_current = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["file_object__file_id", "-is_current", "storage_backend", "relative_path"]
        indexes = [
            models.Index(fields=["storage_backend", "path_role"]),
            models.Index(fields=["is_current", "placement_status"]),
            models.Index(fields=["relative_path"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["file_object", "storage_backend", "physical_ref", "path_role"],
                name="memory_file_physical_placement_ref_role_uniq",
            ),
        ]
        verbose_name = "Физическое размещение файла"
        verbose_name_plural = "Физические размещения файлов"

    def __str__(self):
        return f"{self.storage_backend}:{self.relative_path or self.physical_ref}"


class MemoryFilePathAlias(models.Model):
    class AliasKind(models.TextChoices):
        ORIGINAL = "original", "Первичный путь"
        CURRENT = "current", "Текущий путь"
        PREVIOUS = "previous", "Предыдущий путь"
        EXTERNAL_LINK = "external_link", "Внешняя ссылка"

    file_object = models.ForeignKey(MemoryFileObject, on_delete=models.PROTECT, related_name="path_aliases")
    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="file_path_aliases")
    relative_path = models.CharField(max_length=1000)
    alias_kind = models.CharField(max_length=32, choices=AliasKind.choices, default=AliasKind.CURRENT)
    is_active = models.BooleanField(default=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["source__code", "relative_path"]
        indexes = [
            models.Index(fields=["source", "relative_path"]),
            models.Index(fields=["alias_kind", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["file_object", "source", "relative_path", "alias_kind"],
                name="memory_file_path_alias_uniq",
            ),
        ]
        verbose_name = "Псевдоним пути файла"
        verbose_name_plural = "Псевдонимы путей файлов"

    def __str__(self):
        return f"{self.source.code}:{self.relative_path}"


class MemoryFileVirtualView(models.Model):
    class ViewKind(models.TextChoices):
        BASELINE_AUTO = "baseline_auto", "Автоматическая исходная структура"
        ORGANIZATION_CANDIDATE = "organization_candidate", "Кандидат общей структуры"
        ORGANIZATION_ACCEPTED = "organization_accepted", "Принятая общая структура"
        DEPARTMENT = "department_view", "Представление подразделения"
        USER = "user_view", "Пользовательское представление"
        PROJECT = "project_view", "Проектное представление"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        ACTIVE = "active", "Активно"
        ARCHIVED = "archived", "Архив"

    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="file_virtual_views")
    view_kind = models.CharField(max_length=40, choices=ViewKind.choices)
    slug = models.CharField(max_length=120)
    title = models.CharField(max_length=255)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_file_virtual_views",
        blank=True,
        null=True,
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    is_system = models.BooleanField(default=False)
    baseline_profile = models.CharField(max_length=120, blank=True)
    generated_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["source__code", "view_kind", "slug"]
        indexes = [
            models.Index(fields=["source", "view_kind", "status"]),
            models.Index(fields=["owner_user", "status"]),
            models.Index(fields=["slug"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["source", "view_kind", "slug"], name="memory_file_virtual_view_slug_uniq"),
        ]
        verbose_name = "Виртуальная структура файлов"
        verbose_name_plural = "Виртуальные структуры файлов"

    def __str__(self):
        return f"{self.source.code}:{self.slug}"


class MemoryFileVirtualRule(models.Model):
    class RuleKind(models.TextChoices):
        CLASSIFIER = "classifier", "Классификатор"
        TEMPLATE = "template", "Шаблон"
        MANUAL_PIN = "manual_pin", "Ручное закрепление"
        INHERITED = "inherited", "Унаследовано"

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Предложено"
        ACTIVE = "active", "Активно"
        REJECTED = "rejected", "Отклонено"
        SUPERSEDED = "superseded", "Заменено"

    view = models.ForeignKey(MemoryFileVirtualView, on_delete=models.PROTECT, related_name="rules")
    rule_kind = models.CharField(max_length=32, choices=RuleKind.choices)
    title = models.CharField(max_length=255)
    pattern = models.JSONField(default=dict, blank=True)
    target_template = models.CharField(max_length=1000)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PROPOSED)
    evidence = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["view", "status", "title"]
        indexes = [
            models.Index(fields=["rule_kind", "status"]),
            models.Index(fields=["confidence"]),
        ]
        verbose_name = "Правило виртуальной структуры"
        verbose_name_plural = "Правила виртуальных структур"

    def __str__(self):
        return self.title


class MemoryFileVirtualPlacement(models.Model):
    class PlacementSource(models.TextChoices):
        BASELINE_AUTO = "baseline_auto_v1", "Автоматический baseline"
        INCOMING_AUTO = "incoming_auto_v1", "Автоматический входной разбор"
        USER_MANUAL = "user_manual", "Ручное пользовательское размещение"
        ADMIN_MANUAL = "admin_manual", "Ручное административное размещение"
        LEARNED_RULE = "learned_rule", "Выученное правило"

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Предложено"
        ACCEPTED = "accepted", "Принято"
        REJECTED = "rejected", "Отклонено"
        NEEDS_REVIEW = "needs_review", "Требует ревью"
        SUPERSEDED = "superseded", "Заменено"

    view = models.ForeignKey(MemoryFileVirtualView, on_delete=models.PROTECT, related_name="placements")
    file_object = models.ForeignKey(MemoryFileObject, on_delete=models.PROTECT, related_name="virtual_placements")
    rule = models.ForeignKey(
        MemoryFileVirtualRule,
        on_delete=models.SET_NULL,
        related_name="placements",
        blank=True,
        null=True,
    )
    virtual_path = models.CharField(max_length=1000)
    placement_source = models.CharField(max_length=40, choices=PlacementSource.choices)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PROPOSED)
    review_required = models.BooleanField(default=False)
    evidence = models.JSONField(default=list, blank=True)
    conflicts = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_file_virtual_placements",
        blank=True,
        null=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["view", "virtual_path"]
        indexes = [
            models.Index(fields=["status", "review_required"]),
            models.Index(fields=["placement_source"]),
            models.Index(fields=["virtual_path"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["view", "file_object", "virtual_path"],
                name="memory_file_virtual_placement_uniq",
            ),
            models.CheckConstraint(
                condition=Q(confidence__gte=0) & Q(confidence__lte=1),
                name="memory_file_virtual_placement_confidence_0_1",
            ),
        ]
        verbose_name = "Виртуальное размещение файла"
        verbose_name_plural = "Виртуальные размещения файлов"

    def __str__(self):
        return self.virtual_path


class MemoryFileUsageEvent(models.Model):
    class EventKind(models.TextChoices):
        BASELINE_ACCEPTED = "baseline_accepted", "Baseline принят"
        VIRTUAL_MOVE = "virtual_move", "Виртуальное перемещение"
        FILE_OPENED = "file_opened", "Файл открыт"
        SEARCH_HIT = "search_hit", "Найден через поиск"
        ADMIN_OVERRIDE = "admin_override", "Исправлено администратором"
        PROPOSAL_DECISION = "proposal_decision", "Решение по предложению"

    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="file_usage_events")
    file_object = models.ForeignKey(
        MemoryFileObject,
        on_delete=models.PROTECT,
        related_name="usage_events",
        blank=True,
        null=True,
    )
    view = models.ForeignKey(
        MemoryFileVirtualView,
        on_delete=models.PROTECT,
        related_name="usage_events",
        blank=True,
        null=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_file_usage_events",
        blank=True,
        null=True,
    )
    event_kind = models.CharField(max_length=40, choices=EventKind.choices)
    safe_path_hash = models.CharField(max_length=128, blank=True)
    safe_path_bucket = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["source", "event_kind", "-created_at"]),
            models.Index(fields=["safe_path_hash"]),
            models.Index(fields=["safe_path_bucket"]),
        ]
        verbose_name = "Событие использования файловой структуры"
        verbose_name_plural = "События использования файловой структуры"

    def __str__(self):
        return f"{self.event_kind}:{self.pk}"


class MemoryFileOrganizationProposal(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Предложено"
        NEEDS_MORE_DATA = "needs_more_data", "Нужно больше данных"
        ACCEPTED_VIRTUAL = "accepted_virtual", "Принято как виртуальное правило"
        ACCEPTED_PHYSICAL = "accepted_physical", "Принято для физического переноса"
        REJECTED = "rejected", "Отклонено"
        SUPERSEDED = "superseded", "Заменено"

    proposal_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="file_organization_proposals")
    target_view = models.ForeignKey(
        MemoryFileVirtualView,
        on_delete=models.PROTECT,
        related_name="organization_proposals",
        blank=True,
        null=True,
    )
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PROPOSED)
    proposed_rule = models.JSONField(default=dict, blank=True)
    affected_file_count = models.PositiveIntegerField(default=0)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    evidence = models.JSONField(default=list, blank=True)
    conflicts = models.JSONField(default=list, blank=True)
    metrics = models.JSONField(default=dict, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_memory_file_organization_proposals",
        blank=True,
        null=True,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["source", "status"]),
            models.Index(fields=["proposal_id"]),
            models.Index(fields=["confidence"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(confidence__gte=0) & Q(confidence__lte=1),
                name="memory_file_org_proposal_confidence_0_1",
            ),
        ]
        verbose_name = "Предложение файловой структуры"
        verbose_name_plural = "Предложения файловой структуры"

    def __str__(self):
        return f"{self.status}:{self.title}"


class MemoryFileOrganizationDecision(models.Model):
    class Decision(models.TextChoices):
        ACCEPT_AS_VIRTUAL_RULE = "accept_as_virtual_rule", "Принять как виртуальное правило"
        ACCEPT_FOR_PHYSICAL_MOVE = "accept_for_physical_move", "Принять для физического переноса"
        EDIT = "edit", "Изменить"
        REJECT = "reject", "Отклонить"
        NEEDS_MORE_DATA = "needs_more_data", "Нужно больше данных"

    proposal = models.ForeignKey(MemoryFileOrganizationProposal, on_delete=models.PROTECT, related_name="decisions")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_file_organization_decisions",
    )
    decision = models.CharField(max_length=40, choices=Decision.choices)
    before_state = models.JSONField(default=dict, blank=True)
    after_state = models.JSONField(default=dict, blank=True)
    safe_metadata = models.JSONField(default=dict, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["decision", "-created_at"]),
            models.Index(fields=["proposal", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
        ]
        verbose_name = "Решение по файловой структуре"
        verbose_name_plural = "Решения по файловой структуре"

    def __str__(self):
        return f"{self.decision}:{self.proposal_id}"


class MemoryFileMoveJob(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Запланировано"
        APPROVED = "approved", "Согласовано"
        COPY_STAGED = "copy_staged", "Копия подготовлена"
        VERIFIED = "verified", "Проверено"
        MANAGED_ACTIVE = "managed_active", "Управляемая копия активна"
        SOURCE_QUARANTINED = "source_quarantined", "Исходник в карантине"
        SOURCE_PURGED = "source_purged", "Исходник удален"
        NEEDS_REVIEW = "needs_review", "Требует ревью"
        FAILED = "failed", "Ошибка"

    source = models.ForeignKey(MemorySource, on_delete=models.PROTECT, related_name="file_move_jobs")
    file_object = models.ForeignKey(MemoryFileObject, on_delete=models.PROTECT, related_name="move_jobs")
    proposal = models.ForeignKey(
        MemoryFileOrganizationProposal,
        on_delete=models.PROTECT,
        related_name="move_jobs",
        blank=True,
        null=True,
    )
    source_placement = models.ForeignKey(
        MemoryFilePhysicalPlacement,
        on_delete=models.PROTECT,
        related_name="source_move_jobs",
        blank=True,
        null=True,
    )
    idempotency_key = models.CharField(max_length=180, unique=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PLANNED)
    target_storage_backend = models.CharField(max_length=32, default="managed_fs")
    target_storage_ref = models.CharField(max_length=1200, blank=True)
    target_relative_path = models.CharField(max_length=1000)
    expected_sha256 = models.CharField(max_length=128)
    expected_size_bytes = models.PositiveBigIntegerField(default=0)
    manifest = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_memory_file_move_jobs",
        blank=True,
        null=True,
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    retention_until = models.DateTimeField(blank=True, null=True)
    backup_checkpoint_ref = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["source", "status"]),
            models.Index(fields=["idempotency_key"]),
            models.Index(fields=["retention_until"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(finished_at__isnull=True) | Q(started_at__isnull=True) | Q(started_at__lte=models.F("finished_at")),
                name="memory_file_move_job_time_range",
            ),
        ]
        verbose_name = "Задание переноса файла"
        verbose_name_plural = "Задания переноса файлов"

    def __str__(self):
        return f"{self.status}:{self.idempotency_key}"


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
        verbose_name = "Проблема загрузки памяти"
        verbose_name_plural = "Проблемы загрузки памяти"

    def __str__(self):
        return f"{self.issue_kind}:{self.status}:{self.pk}"


class MemoryReviewAction(models.Model):
    class Action(models.TextChoices):
        ACKNOWLEDGE = "acknowledge", "Принять к сведению"
        ASSIGN = "assign", "Назначить"
        REQUEST_EXPERT_REVIEW = "request_expert_review", "Запросить эксперта"
        RESOLVE = "resolve", "Закрыть"
        IGNORE = "ignore", "Игнорировать"
        REOPEN = "reopen", "Открыть снова"
        COMMENT = "comment", "Комментарий"
        DRY_RUN_REINDEX = "dry_run_reindex", "Пробная переиндексация"
        ENQUEUE_REINDEX = "enqueue_reindex", "Поставить переиндексацию в очередь"
        RETRY_INDEX = "retry_index", "Повторить индексацию"
        DELETE_STALE_INDEX = "delete_stale_index", "Удалить устаревший индекс"
        MARK_INDEX_CLEANED = "mark_index_cleaned", "Отметить индекс очищенным"
        CREATE_ISSUE = "create_issue", "Создать проблему"

    class Decision(models.TextChoices):
        APPLIED = "applied", "Применено"
        QUEUED = "queued", "В очереди"
        REJECTED = "rejected", "Отклонено"
        FAILED = "failed", "Ошибка"
        INFO = "info", "Информация"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_review_actions",
    )
    action = models.CharField(max_length=40, choices=Action.choices)
    decision = models.CharField(max_length=32, choices=Decision.choices, default=Decision.APPLIED)
    issue = models.ForeignKey(
        MemoryIngestionIssue,
        on_delete=models.PROTECT,
        related_name="review_actions",
        blank=True,
        null=True,
    )
    search_document = models.ForeignKey(
        MemorySearchDocument,
        on_delete=models.PROTECT,
        related_name="review_actions",
        blank=True,
        null=True,
    )
    source_object = models.ForeignKey(
        MemorySourceObject,
        on_delete=models.PROTECT,
        related_name="review_actions",
        blank=True,
        null=True,
    )
    index_job = models.ForeignKey(
        "memory.MemoryIndexJob",
        on_delete=models.PROTECT,
        related_name="review_actions",
        blank=True,
        null=True,
    )
    access_audit = models.ForeignKey(
        "memory.MemoryAccessAudit",
        on_delete=models.PROTECT,
        related_name="review_actions",
        blank=True,
        null=True,
    )
    before_state = models.JSONField(default=dict, blank=True)
    after_state = models.JSONField(default=dict, blank=True)
    safe_metadata = models.JSONField(default=dict, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["decision", "-created_at"]),
            models.Index(fields=["issue", "-created_at"]),
            models.Index(fields=["search_document", "-created_at"]),
            models.Index(fields=["source_object", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
        ]
        permissions = [
            ("view_review_queue", "Может просматривать очередь ревью памяти"),
            ("review_issues", "Может ревьюировать проблемы памяти"),
            ("review_privacy_issues", "Может ревьюировать проблемы приватности памяти"),
            ("manage_search_index", "Может управлять поисковым индексом памяти"),
            ("view_memory_access_audit", "Может просматривать аудит доступа к памяти"),
        ]
        verbose_name = "Действие ревью памяти"
        verbose_name_plural = "Действия ревью памяти"

    def __str__(self):
        return f"{self.action}:{self.decision}:{self.pk}"


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


class MemoryWriteRequest(models.Model):
    class TargetScope(models.TextChoices):
        PERSONAL = "personal", "Личная"
        ORGANIZATION = "organization", "Организационная"

    class Status(models.TextChoices):
        QUEUED = "queued", "В очереди"
        PROCESSING = "processing", "Обрабатывается"
        ACCEPTED = "accepted", "Принято"
        CANDIDATE_CREATED = "candidate_created", "Кандидат создан"
        FAILED = "failed", "Ошибка"
        CANCELLED = "cancelled", "Отменено"

    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_write_requests",
    )
    session = models.ForeignKey(
        "ai.ChatSession",
        on_delete=models.SET_NULL,
        related_name="memory_write_requests",
        blank=True,
        null=True,
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
        verbose_name = "Запрос записи памяти"
        verbose_name_plural = "Запросы записи памяти"

    def __str__(self):
        return f"{self.request_id}:{self.target_scope}:{self.status}"


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


class MemoryKnowledgeEvent(models.Model):
    class EventType(models.TextChoices):
        REMEMBERED = "remembered", "Запомнено"
        EDITED = "edited", "Изменено"
        DELETED = "deleted", "Удалено"
        REFLECTED = "reflected", "Отрефлексировано"
        PROMOTED = "promoted", "Повышено"
        REJECTED = "rejected", "Отклонено"
        SECRET_CAPTURED = "secret_captured", "Секрет зафиксирован"

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
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["event_type"]),
            models.Index(fields=["actor", "created_at"]),
        ]
        verbose_name = "Событие знания памяти"
        verbose_name_plural = "События знаний памяти"

    def __str__(self):
        return f"{self.event_type}:{self.event_id}"


class MemoryKnowledgeCandidate(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Предложено"
        NEEDS_REVIEW = "needs_review", "Нужно ревью"
        ACCEPTED = "accepted", "Принято"
        REJECTED = "rejected", "Отклонено"
        MERGED = "merged", "Объединено"
        SUPERSEDED = "superseded", "Заменено"

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
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    decision = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="memory_candidates",
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
        verbose_name = "Кандидат знания памяти"
        verbose_name_plural = "Кандидаты знаний памяти"

    def __str__(self):
        return f"{self.status}:{self.pk}"


class MemoryReflectionRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        RUNNING = "running", "Выполняется"
        SUCCEEDED = "succeeded", "Успешно"
        FAILED = "failed", "Ошибка"

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
        verbose_name = "Запуск рефлексии памяти"
        verbose_name_plural = "Запуски рефлексии памяти"

    def __str__(self):
        return f"{self.status}:{self.pk}"


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


class MemoryIndexJob(models.Model):
    class JobKind(models.TextChoices):
        DISCOVER = "discover", "Обнаружение"
        SYNC = "sync", "Синхронизация"
        REINDEX = "reindex", "Переиндексация"
        EVAL = "eval", "Оценка"
        REMEMBER = "remember", "Запоминание"
        REFLECT = "reflect", "Рефлексия"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        RUNNING = "running", "Выполняется"
        SUCCEEDED = "succeeded", "Успешно"
        FAILED = "failed", "Ошибка"
        CANCELLED = "cancelled", "Отменено"

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
        verbose_name = "Задание индекса памяти"
        verbose_name_plural = "Задания индекса памяти"

    def __str__(self):
        return f"{self.job_kind}:{self.status}:{self.pk}"


class MemoryExternalConnectorJob(models.Model):
    """Database-backed external connector queue job."""

    job_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source_code = models.CharField(max_length=120)
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
            models.Index(fields=["idempotency_key"]),
            models.Index(fields=["job_id"]),
        ]
        verbose_name = "Задание внешнего коннектора"
        verbose_name_plural = "Задания внешних коннекторов"

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
