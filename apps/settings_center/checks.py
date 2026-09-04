from django.core.checks import Error, Warning, register
from django.db import connection

from .document_registry import get_document_registry
from .document_migration import plan_migration


_MIGRATION_CODE_BY_CLASSIFICATION = {
    "migration_required": "migration_required",
    "ambiguous_drift": "ambiguous_legacy",
    "env_override": "env_override",
    "conflict": "conflict",
    "security_review_required": "security_review_required",
}
_MIGRATION_BLOCKING_CLASSES = frozenset(_MIGRATION_CODE_BY_CLASSIFICATION)


def probe_settings_migration_health():
    """Return a safe readiness summary for legacy settings migration.

    This probe deliberately exposes neither the migration reason, payload,
    filesystem path, nor audit metadata.  It is separate from the active
    database-document probe because legacy migration must remain observable
    while the new backend is not yet enabled for a document.
    """

    try:
        legacy_ids = tuple(
            spec.document_id
            for spec in get_document_registry().all()
            if spec.storage_policy == "database_override"
            and spec.active_backend == "legacy_file"
        )
        plans = plan_migration(legacy_ids) if legacy_ids else ()
    except Exception as exc:  # noqa: BLE001 - DB vendors use different wrappers
        from django.db import DatabaseError

        if isinstance(exc, DatabaseError) or isinstance(exc.__cause__, DatabaseError):
            return {
                "status": "error",
                "code": "store_unavailable",
                "documents": {},
            }
        # Planning errors are intentionally collapsed to a stable operational
        # code.  The exception text may contain paths or configuration values.
        return {
            "status": "error",
            "code": "migration_unavailable",
            "documents": {},
        }

    documents = {}
    for plan in plans:
        classification = str(plan.classification)
        if classification not in _MIGRATION_BLOCKING_CLASSES:
            continue
        documents[plan.document_id] = {
            "classification": classification,
            "code": _MIGRATION_CODE_BY_CLASSIFICATION[classification],
        }
    return {
        "status": "degraded" if documents else "ok",
        "documents": documents,
    }


@register("contracts")
def check_settings_document_backend(app_configs, **kwargs):
    database_documents = [
        spec.document_id
        for spec in get_document_registry().all()
        if spec.active_backend == "database"
    ]
    if not database_documents or connection.vendor == "postgresql":
        return []

    message = (
        "Документы настроек переключены на database backend, но основная БД не PostgreSQL."
    )
    hint = (
        "Чтение доступно для локальной диагностики, однако writer отключён: "
        "используйте PostgreSQL для проверки и эксплуатации. Документы: "
        + ", ".join(database_documents)
    )
    # Сейчас реальные specs активируются поэтапно. Ошибка нужна в production;
    # warning сохраняет поддерживаемую SQLite-среду локальных read-only тестов.
    from django.conf import settings

    check_type = Error if getattr(settings, "DJANGO_ENV", "development") == "production" else Warning
    return [check_type(message, hint=hint, id="settings_center.E001" if check_type is Error else "settings_center.W001")]


@register("contracts")
def check_settings_document_migration(app_configs, **kwargs):
    """Warn about legacy database_override documents not ready for import."""

    health = probe_settings_migration_health()
    if health["status"] == "error":
        return [
            Warning(
                "Состояние миграции документов настроек недоступно.",
                hint="Проверьте доступность хранилища настроек перед миграцией.",
                id="settings_center.W002",
            )
        ]
    if not health["documents"]:
        return []
    entries = ", ".join(
        f"{document_id} ({item['classification']})"
        for document_id, item in sorted(health["documents"].items())
    )
    return [
        Warning(
            "Некоторые документы настроек не готовы к миграции.",
            hint="Проверьте документы: " + entries,
            id="settings_center.W002",
        )
    ]
