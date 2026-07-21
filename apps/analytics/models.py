from django.conf import settings
from django.db import models
from django.db.models import Q


class AnalyticsSource(models.Model):
    class SourceKind(models.TextChoices):
        MEMORY = "memory", "Память"
        DJANGO_MODEL = "django_model", "Модель Django"
        EMAIL_IMAP = "email_imap", "Почта IMAP"
        FILE_SHARE = "file_share", "Файловый ресурс"
        DMS = "dms", "DMS"
        EXTERNAL_API = "external_api", "Внешний API"

    class Status(models.TextChoices):
        ENABLED = "enabled", "Включен"
        DISABLED = "disabled", "Отключен"
        ERROR = "error", "Ошибка"

    code = models.CharField(max_length=120, unique=True)
    title = models.CharField(max_length=255)
    source_kind = models.CharField(max_length=32, choices=SourceKind.choices)
    owner = models.CharField(max_length=120)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ENABLED)
    scope_tokens = models.JSONField(default=list, blank=True)
    sensitivity = models.CharField(max_length=32, default="internal")
    config = models.JSONField(default=dict, blank=True)
    watermarks = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(blank=True, null=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["source_kind"]),
            models.Index(fields=["status"]),
            models.Index(fields=["sensitivity"]),
        ]
        verbose_name = "Источник аналитики"
        verbose_name_plural = "Источники аналитики"

    def __str__(self):
        return self.code


class AnalyticsExtractionRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        RUNNING = "running", "Выполняется"
        SUCCEEDED = "succeeded", "Завершен"
        FAILED = "failed", "Ошибка"
        CANCELLED = "cancelled", "Отменен"

    source = models.ForeignKey(AnalyticsSource, on_delete=models.PROTECT, related_name="extraction_runs")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    dry_run = models.BooleanField(default=False)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    metrics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="analytics_extraction_runs",
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
                name="analytics_extraction_run_time_range",
            ),
        ]
        verbose_name = "Запуск извлечения аналитики"
        verbose_name_plural = "Запуски извлечения аналитики"

    def __str__(self):
        return f"{self.source.code}:{self.status}:{self.pk}"


class AnalyticsContentObject(models.Model):
    source = models.ForeignKey(AnalyticsSource, on_delete=models.PROTECT, related_name="content_objects")
    source_object_id = models.CharField(max_length=500)
    source_uri = models.CharField(max_length=1000, blank=True)
    content_kind = models.CharField(max_length=64)
    title = models.CharField(max_length=500, blank=True)
    raw_sha256 = models.CharField(max_length=80, blank=True)
    normalized_text_sha256 = models.CharField(max_length=80, blank=True)
    near_duplicate_key = models.CharField(max_length=120, blank=True)
    business_key = models.CharField(max_length=255, blank=True)
    scope_tokens = models.JSONField(default=list, blank=True)
    sensitivity = models.CharField(max_length=32, default="internal")
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    source_updated_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["source__code", "source_object_id"]
        indexes = [
            models.Index(fields=["source", "source_object_id"]),
            models.Index(fields=["content_kind"]),
            models.Index(fields=["raw_sha256"]),
            models.Index(fields=["normalized_text_sha256"]),
            models.Index(fields=["business_key"]),
            models.Index(fields=["is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["source", "source_object_id"], name="analytics_content_source_object_uniq"),
        ]
        verbose_name = "Объект содержимого аналитики"
        verbose_name_plural = "Объекты содержимого аналитики"

    def __str__(self):
        return f"{self.source.code}:{self.source_object_id}"


class AnalyticsExtractionPacket(models.Model):
    packet_id = models.CharField(max_length=160, unique=True)
    source = models.ForeignKey(AnalyticsSource, on_delete=models.PROTECT, related_name="extraction_packets")
    content_object = models.ForeignKey(
        AnalyticsContentObject,
        on_delete=models.PROTECT,
        related_name="extraction_packets",
        blank=True,
        null=True,
    )
    packet = models.JSONField(default=dict)
    scope_tokens = models.JSONField(default=list, blank=True)
    sensitivity = models.CharField(max_length=32, default="internal")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["source", "-created_at"]),
            models.Index(fields=["packet_id"]),
            models.Index(fields=["sensitivity"]),
        ]
        verbose_name = "Пакет извлечения аналитики"
        verbose_name_plural = "Пакеты извлечения аналитики"

    def __str__(self):
        return self.packet_id


class AnalyticsEvidenceRef(models.Model):
    content_object = models.ForeignKey(AnalyticsContentObject, on_delete=models.PROTECT, related_name="evidence_refs")
    evidence_id = models.CharField(max_length=160, unique=True)
    ref_kind = models.CharField(max_length=64)
    ref_value = models.CharField(max_length=1000)
    authority_rank = models.PositiveIntegerField(default=100)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["authority_rank", "evidence_id"]
        indexes = [
            models.Index(fields=["ref_kind"]),
            models.Index(fields=["authority_rank"]),
        ]
        verbose_name = "Ссылка на доказательство аналитики"
        verbose_name_plural = "Ссылки на доказательства аналитики"

    def __str__(self):
        return self.evidence_id


class AnalyticsDuplicateCandidate(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Предложен"
        MERGED = "merged", "Объединен"
        VERSIONED = "versioned", "Версионирован"
        REJECTED = "rejected", "Отклонен"

    canonical_object = models.ForeignKey(
        AnalyticsContentObject,
        on_delete=models.PROTECT,
        related_name="canonical_duplicate_candidates",
    )
    duplicate_object = models.ForeignKey(
        AnalyticsContentObject,
        on_delete=models.PROTECT,
        related_name="duplicate_candidates",
    )
    match_kind = models.CharField(max_length=64)
    score = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED)
    rationale = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="analytics_duplicate_reviews",
        blank=True,
        null=True,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["match_kind"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["canonical_object", "duplicate_object", "match_kind"],
                name="analytics_duplicate_candidate_uniq",
            ),
            models.CheckConstraint(
                condition=Q(score__gte=0) & Q(score__lte=1),
                name="analytics_duplicate_score_0_1",
            ),
        ]
        verbose_name = "Кандидат-дубликат аналитики"
        verbose_name_plural = "Кандидаты-дубликаты аналитики"

    def __str__(self):
        return f"{self.match_kind}:{self.status}:{self.pk}"


class AnalyticsFact(models.Model):
    fact_id = models.CharField(max_length=160, unique=True)
    fact_type = models.CharField(max_length=120)
    event_time = models.DateTimeField(blank=True, null=True)
    dimensions = models.JSONField(default=dict, blank=True)
    measures = models.JSONField(default=dict, blank=True)
    evidence_refs = models.JSONField(default=list, blank=True)
    semantic_hash = models.CharField(max_length=128)
    scope_tokens = models.JSONField(default=list, blank=True)
    sensitivity = models.CharField(max_length=32, default="internal")
    source_packet = models.ForeignKey(
        AnalyticsExtractionPacket,
        on_delete=models.PROTECT,
        related_name="facts",
        blank=True,
        null=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fact_type", "-event_time", "-id"]
        indexes = [
            models.Index(fields=["fact_type"]),
            models.Index(fields=["semantic_hash"]),
            models.Index(fields=["event_time"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["sensitivity"]),
        ]
        verbose_name = "Факт аналитики"
        verbose_name_plural = "Факты аналитики"

    def __str__(self):
        return self.fact_id


class AnalyticsMetricSnapshot(models.Model):
    metric_code = models.CharField(max_length=120)
    window_start = models.DateTimeField(blank=True, null=True)
    window_end = models.DateTimeField(blank=True, null=True)
    value = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    dimensions = models.JSONField(default=dict, blank=True)
    source_fact_count = models.PositiveIntegerField(default=0)
    dataset_path = models.CharField(max_length=1000, blank=True)
    scope_tokens = models.JSONField(default=list, blank=True)
    sensitivity = models.CharField(max_length=32, default="internal")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["metric_code", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["metric_code"]),
            models.Index(fields=["window_start", "window_end"]),
            models.Index(fields=["sensitivity"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(window_end__isnull=True) | Q(window_start__isnull=True) | Q(window_start__lte=models.F("window_end")),
                name="analytics_metric_snapshot_time_range",
            ),
        ]
        verbose_name = "Снимок метрики аналитики"
        verbose_name_plural = "Снимки метрик аналитики"

    def __str__(self):
        return f"{self.metric_code}:{self.value}"


class AnalyticsSignal(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Открыт"
        DIAGNOSING = "diagnosing", "Диагностика"
        ROUTED = "routed", "Маршрутизирован"
        RESOLVED = "resolved", "Закрыт"
        IGNORED = "ignored", "Игнорируется"

    class Severity(models.TextChoices):
        INFO = "info", "Информация"
        WARNING = "warning", "Предупреждение"
        HIGH = "high", "Высокая"
        CRITICAL = "critical", "Критическая"

    signal_id = models.CharField(max_length=160, unique=True)
    monitor_code = models.CharField(max_length=120)
    metric_snapshot = models.ForeignKey(
        AnalyticsMetricSnapshot,
        on_delete=models.PROTECT,
        related_name="signals",
        blank=True,
        null=True,
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.WARNING)
    message = models.TextField()
    evidence = models.JSONField(default=list, blank=True)
    scope_tokens = models.JSONField(default=list, blank=True)
    sensitivity = models.CharField(max_length=32, default="internal")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["monitor_code"]),
            models.Index(fields=["status"]),
            models.Index(fields=["severity"]),
        ]
        verbose_name = "Сигнал аналитики"
        verbose_name_plural = "Сигналы аналитики"

    def __str__(self):
        return self.signal_id


class AnalyticsDiagnosticRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        RUNNING = "running", "Выполняется"
        SUCCEEDED = "succeeded", "Завершен"
        FAILED = "failed", "Ошибка"

    signal = models.ForeignKey(AnalyticsSignal, on_delete=models.PROTECT, related_name="diagnostic_runs")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    dry_run = models.BooleanField(default=False)
    evidence_packet = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="analytics_diagnostic_runs",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["signal", "-created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["dry_run"]),
        ]
        verbose_name = "Запуск диагностики аналитики"
        verbose_name_plural = "Запуски диагностики аналитики"

    def __str__(self):
        return f"{self.signal_id}:{self.status}:{self.pk}"


class AnalyticsCase(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        ROUTED = "routed", "Маршрутизирован"
        IN_PROGRESS = "in_progress", "В работе"
        RESOLVED = "resolved", "Закрыт"
        CANCELLED = "cancelled", "Отменен"

    case_id = models.CharField(max_length=160, unique=True)
    signal = models.ForeignKey(AnalyticsSignal, on_delete=models.PROTECT, related_name="cases")
    route_code = models.CharField(max_length=120)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["case_id"]),
            models.Index(fields=["route_code"]),
            models.Index(fields=["status"]),
        ]
        verbose_name = "Случай аналитики"
        verbose_name_plural = "Случаи аналитики"

    def __str__(self):
        return self.case_id


class AnalyticsMetricCandidate(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "proposed", "Предложен"
        NEEDS_REVIEW = "needs_review", "Требует проверки"
        ACCEPTED = "accepted", "Принят"
        REJECTED = "rejected", "Отклонен"

    candidate_id = models.CharField(max_length=160, unique=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PROPOSED)
    title = models.CharField(max_length=255)
    rationale = models.TextField()
    proposed_contract = models.JSONField(default=dict, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="analytics_metric_candidate_reviews",
        blank=True,
        null=True,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["candidate_id"]),
            models.Index(fields=["status"]),
        ]
        verbose_name = "Кандидат метрики аналитики"
        verbose_name_plural = "Кандидаты метрик аналитики"

    def __str__(self):
        return self.candidate_id


class AnalyticsSampleManifest(models.Model):
    manifest_id = models.CharField(max_length=160, unique=True)
    scope_rule_code = models.CharField(max_length=120)
    source_codes = models.JSONField(default=list, blank=True)
    selected_object_ids = models.JSONField(default=list, blank=True)
    sampling_strategy = models.CharField(max_length=64)
    limits = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["manifest_id"]),
            models.Index(fields=["scope_rule_code"]),
            models.Index(fields=["sampling_strategy"]),
        ]
        verbose_name = "Манифест выборки аналитики"
        verbose_name_plural = "Манифесты выборок аналитики"

    def __str__(self):
        return self.manifest_id


class AnalyticsAccessAudit(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="analytics_access_audits",
    )
    action = models.CharField(max_length=120)
    decision = models.CharField(max_length=32)
    scope_tokens = models.JSONField(default=list, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["action", "decision"]),
        ]
        verbose_name = "Аудит доступа к аналитике"
        verbose_name_plural = "Аудит доступа к аналитике"

    def __str__(self):
        return f"{self.action}:{self.decision}:{self.pk}"
