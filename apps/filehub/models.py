"""Models for the File Source Auto Organization contour.

ADR-0030 decision 5: this contour was extracted from ``apps.memory`` into
``apps.filehub`` as a pure move (no functional change). ``db_table`` is
pinned to the original Django-generated table names so the physical tables
are untouched by the move. See ``apps/filehub/README.md`` for the freeze
status (ADR-0025).
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


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
    source = models.ForeignKey("memory.MemorySource", on_delete=models.PROTECT, related_name="file_objects")
    current_version = models.ForeignKey(
        "filehub.MemoryFileObjectVersion",
        on_delete=models.SET_NULL,
        related_name="+",
        blank=True,
        null=True,
    )
    current_physical_placement = models.ForeignKey(
        "filehub.MemoryFilePhysicalPlacement",
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
        db_table = "memory_memoryfileobject"
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
        "memory.MemorySourceObject",
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
        db_table = "memory_memoryfileobjectversion"
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
        "memory.MemorySourceObject",
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
        db_table = "memory_memoryfilephysicalplacement"
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
    source = models.ForeignKey("memory.MemorySource", on_delete=models.PROTECT, related_name="file_path_aliases")
    relative_path = models.CharField(max_length=1000)
    alias_kind = models.CharField(max_length=32, choices=AliasKind.choices, default=AliasKind.CURRENT)
    is_active = models.BooleanField(default=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "memory_memoryfilepathalias"
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

    source = models.ForeignKey("memory.MemorySource", on_delete=models.PROTECT, related_name="file_virtual_views")
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
        db_table = "memory_memoryfilevirtualview"
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
        db_table = "memory_memoryfilevirtualrule"
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
        db_table = "memory_memoryfilevirtualplacement"
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

    source = models.ForeignKey("memory.MemorySource", on_delete=models.PROTECT, related_name="file_usage_events")
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
        db_table = "memory_memoryfileusageevent"
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
    source = models.ForeignKey("memory.MemorySource", on_delete=models.PROTECT, related_name="file_organization_proposals")
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
        db_table = "memory_memoryfileorganizationproposal"
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
        db_table = "memory_memoryfileorganizationdecision"
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

    source = models.ForeignKey("memory.MemorySource", on_delete=models.PROTECT, related_name="file_move_jobs")
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
        db_table = "memory_memoryfilemovejob"
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
