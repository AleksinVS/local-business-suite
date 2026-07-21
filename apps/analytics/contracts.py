"""Валидаторы доменных контрактов аналитики.

Содержит правила предметной области аналитики: реестр датасетов, источники,
scope-правила, бизнес-факты, метрики, мониторы, диагностические playbook-и,
workflow-маршруты, правила дедупликации и профили хранения. По правилам 3 и 5
AGENTS.md эти доменные правила живут в приложении аналитики, а не в ядре.

Универсальные JSON-примитивы (``_ensure_*``) импортируются из
``apps.core.json_utils`` (обратной зависимости нет).
"""
from django.core.exceptions import ValidationError

from apps.core.json_utils import (
    _ensure_contract_list,
    _ensure_list_of_strings,
    _ensure_unique_code,
)


REQUIRED_DATASET_KEYS = {
    "code",
    "layer",
    "path",
    "owner",
    "refresh_mode",
    "grain",
    "schema_version",
    "description",
}

REQUIRED_ANALYTICS_SOURCE_KEYS = {
    "code",
    "title",
    "source_kind",
    "owner",
    "enabled",
    "sync_mode",
    "schedule",
    "scope_tokens",
    "sensitivity",
    "retention_profile",
    "config",
}

REQUIRED_ANALYTICS_SCOPE_RULE_KEYS = {
    "code",
    "title",
    "owner",
    "sources",
    "include",
    "exclude",
    "limits",
    "sampling",
    "requires_audit",
}

REQUIRED_ANALYTICS_BUSINESS_FACT_KEYS = {
    "code",
    "title",
    "owner",
    "description",
    "dimensions",
    "measures",
    "sensitivity",
}

REQUIRED_ANALYTICS_METRIC_KEYS = {
    "code",
    "title",
    "owner",
    "fact_type",
    "aggregation",
    "measure",
    "window",
    "refresh_mode",
    "scope_tokens",
    "sensitivity",
}

REQUIRED_ANALYTICS_MONITOR_KEYS = {
    "code",
    "title",
    "owner",
    "metric_code",
    "condition",
    "threshold",
    "severity",
    "workflow_route",
    "enabled",
}

REQUIRED_ANALYTICS_DIAGNOSTIC_PLAYBOOK_KEYS = {
    "code",
    "title",
    "owner",
    "signal_kinds",
    "allowed_evidence",
    "autonomous_actions",
    "requires_human_review",
}

REQUIRED_ANALYTICS_WORKFLOW_ROUTE_KEYS = {
    "code",
    "title",
    "owner",
    "target",
    "requires_confirmation",
    "allowed_autonomous_actions",
}

REQUIRED_ANALYTICS_DEDUP_RULE_KEYS = {
    "code",
    "owner",
    "exact_hash_fields",
    "near_duplicate_fields",
    "semantic_fields",
    "authority_priority",
    "auto_merge_exact",
    "review_near_duplicates",
}

REQUIRED_ANALYTICS_RETENTION_PROFILE_KEYS = {
    "code",
    "owner",
    "raw_retention_days",
    "normalized_retention_days",
    "fact_retention_days",
    "audit_retention_days",
}

ANALYTICS_SOURCE_KIND_VALUES = {"memory", "django_model", "email_imap", "file_share", "dms", "external_api"}
ANALYTICS_SYNC_MODE_VALUES = {"scheduled", "manual", "event", "hybrid"}
ANALYTICS_SENSITIVITY_VALUES = {"public", "internal", "confidential", "pii_redacted", "pii_original", "secret"}
ANALYTICS_AGGREGATION_VALUES = {"count", "sum", "avg", "min", "max"}
ANALYTICS_MONITOR_CONDITION_VALUES = {"gt", "gte", "lt", "lte", "eq", "neq"}
ANALYTICS_MONITOR_SEVERITY_VALUES = {"info", "warning", "high", "critical"}


def validate_dataset_registry_payload(payload):
    if not isinstance(payload, list):
        raise ValidationError("Реестр аналитических датасетов должен быть JSON-массивом.")
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"Датасет #{index} должен быть JSON-объектом.")
        missing = REQUIRED_DATASET_KEYS - set(item.keys())
        if missing:
            raise ValidationError(
                f"Датасет '{item.get('code', index)}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing))}."
            )


def validate_analytics_sources_payload(payload):
    _ensure_contract_list(payload, "Analytics sources", REQUIRED_ANALYTICS_SOURCE_KEYS)
    codes = set()
    for item in payload:
        code = _ensure_unique_code(item, codes, "Analytics source")
        if item.get("source_kind") not in ANALYTICS_SOURCE_KIND_VALUES:
            raise ValidationError(f"Analytics source '{code}' содержит недопустимый source_kind.")
        if item.get("sync_mode") not in ANALYTICS_SYNC_MODE_VALUES:
            raise ValidationError(f"Analytics source '{code}' содержит недопустимый sync_mode.")
        if item.get("sensitivity") not in ANALYTICS_SENSITIVITY_VALUES:
            raise ValidationError(f"Analytics source '{code}' содержит недопустимый sensitivity.")
        if not isinstance(item.get("enabled"), bool):
            raise ValidationError(f"Поле enabled у analytics source '{code}' должно быть boolean.")
        if item.get("schedule") is not None and not isinstance(item.get("schedule"), str):
            raise ValidationError(f"Поле schedule у analytics source '{code}' должно быть строкой или null.")
        _ensure_list_of_strings(item.get("scope_tokens"), f"Поле scope_tokens у analytics source '{code}'")
        if not isinstance(item.get("config"), dict):
            raise ValidationError(f"Поле config у analytics source '{code}' должно быть JSON-объектом.")
        if item["source_kind"] == "email_imap" and not item["config"].get("mailbox_code"):
            raise ValidationError(f"Email IMAP source '{code}' должен содержать config.mailbox_code.")


def validate_analytics_scope_rules_payload(payload):
    _ensure_contract_list(payload, "Analytics scope rules", REQUIRED_ANALYTICS_SCOPE_RULE_KEYS)
    codes = set()
    for item in payload:
        code = _ensure_unique_code(item, codes, "Analytics scope rule")
        _ensure_list_of_strings(item.get("sources"), f"Поле sources у analytics scope rule '{code}'")
        if not item["sources"]:
            raise ValidationError(f"Analytics scope rule '{code}' должен содержать хотя бы один source.")
        for key in ("include", "exclude", "limits", "sampling"):
            if not isinstance(item.get(key), dict):
                raise ValidationError(f"Поле {key} у analytics scope rule '{code}' должно быть JSON-объектом.")
        if not isinstance(item.get("requires_audit"), bool):
            raise ValidationError(f"Поле requires_audit у analytics scope rule '{code}' должно быть boolean.")
        strategy = item["sampling"].get("strategy")
        if strategy not in {"all", "latest", "top_risk", "stratified", "random", "changed_since_watermark", "graph_neighborhood", "signal_evidence_window"}:
            raise ValidationError(f"Analytics scope rule '{code}' содержит недопустимую sampling.strategy.")
        for limit_key, value in item["limits"].items():
            if type(value) is not int or value <= 0:
                raise ValidationError(f"Limit '{limit_key}' у analytics scope rule '{code}' должен быть положительным числом.")


def validate_analytics_business_facts_payload(payload):
    _ensure_contract_list(payload, "Analytics business facts", REQUIRED_ANALYTICS_BUSINESS_FACT_KEYS)
    codes = set()
    for item in payload:
        code = _ensure_unique_code(item, codes, "Analytics business fact")
        _ensure_list_of_strings(item.get("dimensions"), f"Поле dimensions у analytics business fact '{code}'")
        _ensure_list_of_strings(item.get("measures"), f"Поле measures у analytics business fact '{code}'")
        if item.get("sensitivity") not in ANALYTICS_SENSITIVITY_VALUES:
            raise ValidationError(f"Analytics business fact '{code}' содержит недопустимый sensitivity.")


def validate_analytics_metrics_payload(payload):
    _ensure_contract_list(payload, "Analytics metrics", REQUIRED_ANALYTICS_METRIC_KEYS)
    codes = set()
    for item in payload:
        code = _ensure_unique_code(item, codes, "Analytics metric")
        if item.get("aggregation") not in ANALYTICS_AGGREGATION_VALUES:
            raise ValidationError(f"Analytics metric '{code}' содержит недопустимую aggregation.")
        if item.get("refresh_mode") not in {"scheduled", "event", "manual"}:
            raise ValidationError(f"Analytics metric '{code}' содержит недопустимый refresh_mode.")
        if item.get("sensitivity") not in ANALYTICS_SENSITIVITY_VALUES:
            raise ValidationError(f"Analytics metric '{code}' содержит недопустимый sensitivity.")
        _ensure_list_of_strings(item.get("scope_tokens"), f"Поле scope_tokens у analytics metric '{code}'")


def validate_analytics_monitors_payload(payload):
    _ensure_contract_list(payload, "Analytics monitors", REQUIRED_ANALYTICS_MONITOR_KEYS)
    codes = set()
    for item in payload:
        code = _ensure_unique_code(item, codes, "Analytics monitor")
        if item.get("condition") not in ANALYTICS_MONITOR_CONDITION_VALUES:
            raise ValidationError(f"Analytics monitor '{code}' содержит недопустимую condition.")
        if item.get("severity") not in ANALYTICS_MONITOR_SEVERITY_VALUES:
            raise ValidationError(f"Analytics monitor '{code}' содержит недопустимую severity.")
        if type(item.get("threshold")) not in (int, float):
            raise ValidationError(f"Поле threshold у analytics monitor '{code}' должно быть числом.")
        if not isinstance(item.get("enabled"), bool):
            raise ValidationError(f"Поле enabled у analytics monitor '{code}' должно быть boolean.")


def validate_analytics_diagnostic_playbooks_payload(payload):
    _ensure_contract_list(payload, "Analytics diagnostic playbooks", REQUIRED_ANALYTICS_DIAGNOSTIC_PLAYBOOK_KEYS)
    codes = set()
    for item in payload:
        code = _ensure_unique_code(item, codes, "Analytics diagnostic playbook")
        for key in ("signal_kinds", "allowed_evidence", "autonomous_actions"):
            _ensure_list_of_strings(item.get(key), f"Поле {key} у analytics diagnostic playbook '{code}'")
        if not isinstance(item.get("requires_human_review"), bool):
            raise ValidationError(f"Поле requires_human_review у analytics diagnostic playbook '{code}' должно быть boolean.")


def validate_analytics_workflow_routes_payload(payload):
    _ensure_contract_list(payload, "Analytics workflow routes", REQUIRED_ANALYTICS_WORKFLOW_ROUTE_KEYS)
    codes = set()
    for item in payload:
        code = _ensure_unique_code(item, codes, "Analytics workflow route")
        if item.get("target") not in {"analytics_case", "workorder", "external_task", "notification"}:
            raise ValidationError(f"Analytics workflow route '{code}' содержит недопустимый target.")
        if not isinstance(item.get("requires_confirmation"), bool):
            raise ValidationError(f"Поле requires_confirmation у analytics workflow route '{code}' должно быть boolean.")
        _ensure_list_of_strings(item.get("allowed_autonomous_actions"), f"Поле allowed_autonomous_actions у analytics workflow route '{code}'")


def validate_analytics_dedup_rules_payload(payload):
    _ensure_contract_list(payload, "Analytics dedup rules", REQUIRED_ANALYTICS_DEDUP_RULE_KEYS)
    codes = set()
    for item in payload:
        code = _ensure_unique_code(item, codes, "Analytics dedup rule")
        for key in ("exact_hash_fields", "near_duplicate_fields", "semantic_fields", "authority_priority"):
            _ensure_list_of_strings(item.get(key), f"Поле {key} у analytics dedup rule '{code}'")
            if not item.get(key):
                raise ValidationError(f"Поле {key} у analytics dedup rule '{code}' должно быть непустым списком.")
        for key in ("auto_merge_exact", "review_near_duplicates"):
            if not isinstance(item.get(key), bool):
                raise ValidationError(f"Поле {key} у analytics dedup rule '{code}' должно быть boolean.")


def validate_analytics_retention_profiles_payload(payload):
    _ensure_contract_list(payload, "Analytics retention profiles", REQUIRED_ANALYTICS_RETENTION_PROFILE_KEYS)
    codes = set()
    for item in payload:
        code = _ensure_unique_code(item, codes, "Analytics retention profile")
        for key in ("raw_retention_days", "normalized_retention_days", "fact_retention_days", "audit_retention_days"):
            if type(item.get(key)) is not int or item[key] < 0:
                raise ValidationError(f"Поле {key} у analytics retention profile '{code}' должно быть неотрицательным числом.")
