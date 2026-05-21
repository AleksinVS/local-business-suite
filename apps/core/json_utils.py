import json
from pathlib import Path

from django.core.exceptions import ValidationError


ROLE_SCOPE_VALUES = {
    "none",
    "all",
    "visible",
    "authored",
    "assigned",
    "assigned_or_unassigned",
    "assigned_or_unassigned_or_authored",
}

REQUIRED_ROLE_KEYS = {
    "view_scope",
    "create_workorder",
    "edit_scope",
    "comment_scope",
    "upload_attachment_scope",
    "confirm_closure_scope",
    "rate_scope",
    "transition_scope",
    "transition_targets",
    "manage_inventory",
    "manage_board_columns",
    "manage_assignments",
    "view_analytics",
    "manage_departments",
    "manage_roles",
}

BACKWARD_COMPAT_ROLE_DEFAULT_KEYS = {
    "view_analytics",
    "manage_departments",
    "manage_roles",
}

REQUIRED_WORKFLOW_KEYS = {
    "statuses",
    "transitions",
}

REQUIRED_INTEGRATION_KEYS = {
    "code",
    "name",
    "owner",
    "transport",
    "mode",
    "direction",
    "status",
    "source_of_truth",
    "payloads",
}

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

ANALYTICS_SOURCE_KIND_VALUES = {"memory", "email_imap", "file_share", "dms", "external_api"}
ANALYTICS_SYNC_MODE_VALUES = {"scheduled", "manual", "event", "hybrid"}
ANALYTICS_SENSITIVITY_VALUES = {"public", "internal", "confidential", "pii_redacted", "pii_original", "secret"}
ANALYTICS_AGGREGATION_VALUES = {"count", "sum", "avg", "min", "max"}
ANALYTICS_MONITOR_CONDITION_VALUES = {"gt", "gte", "lt", "lte", "eq", "neq"}
ANALYTICS_MONITOR_SEVERITY_VALUES = {"info", "warning", "high", "critical"}

REQUIRED_TASK_BRIEF_KEYS = {
    "id",
    "title",
    "status",
    "requested_by",
    "target_modules",
    "objective",
    "constraints",
    "deliverables",
    "acceptance_checks",
}

REQUIRED_CHANGE_PLAN_KEYS = {
    "brief_id",
    "title",
    "status",
    "summary",
    "assumptions",
    "affected_files",
    "steps",
    "verification",
    "risks",
}

REQUIRED_AI_REGISTRY_KEYS = {
    "version",
    "name",
    "description",
    "agent_orchestrator",
    "tool_protocol",
    "tool_catalog",
    "task_type_catalog",
    "identity_model",
    "execution_policy",
}

REQUIRED_AI_TOOLS_ROOT_KEYS = {
    "version",
    "name",
    "description",
    "default_policies",
    "tools",
}

REQUIRED_AI_TOOL_KEYS = {
    "id",
    "title",
    "domain",
    "mode",
    "execution_mode",
    "description",
    "inputs",
    "outputs",
    "required_role_scope",
}

REQUIRED_AI_TASK_TYPES_ROOT_KEYS = {
    "version",
    "name",
    "description",
    "task_types",
}

REQUIRED_AI_TASK_TYPE_KEYS = {
    "id",
    "title",
    "mode",
    "description",
    "allowed_tools",
    "requires_confirmation",
    "output_mode",
    "example_requests",
}

REQUIRED_MEMORY_SOURCE_KEYS = {
    "code",
    "title",
    "description",
    "source_kind",
    "domain",
    "owner",
    "enabled",
    "sync_mode",
    "schedule",
    "source_ref",
    "scope_rule",
    "sensitivity",
    "pii_policy",
    "versioning_mode",
    "retention_policy",
    "extractor_profile",
    "chunking_profile",
    "index_profiles",
    "ignore_patterns",
}

REQUIRED_MEMORY_INGESTION_PROFILES_ROOT_KEYS = {
    "version",
    "name",
    "description",
    "adapter_profiles",
    "parser_profiles",
    "ocr_profiles",
    "limit_profiles",
    "profiles",
}

REQUIRED_MEMORY_INGESTION_PROFILE_KEYS = {
    "adapter_profile",
    "parser_profile",
    "ocr_profile",
    "limit_profile",
    "raw_mode",
    "acl_mode",
    "partial_indexing",
    "issue_policy",
}

REQUIRED_MEMORY_GRAPH_SCHEMA_ROOT_KEYS = {
    "schema_version",
    "name",
    "description",
    "entity_types",
    "relation_types",
    "attribute_types",
    "canonicalization_rules",
    "negative_examples",
    "forbidden_patterns",
    "confidence_thresholds",
    "auto_accept_policy",
    "review_policy",
    "department_evidence",
    "changelog",
}

REQUIRED_MEMORY_PROFILES_ROOT_KEYS = {
    "chunking_profiles",
    "extractor_profiles",
    "embedding_profiles",
    "index_profiles",
    "ranking_profiles",
}

REQUIRED_MEMORY_CHUNKING_PROFILE_KEYS = {
    "max_tokens",
    "overlap_tokens",
    "preserve_fields",
}

REQUIRED_MEMORY_EMBEDDING_PROFILE_KEYS = {
    "provider",
    "model",
    "dimensions",
    "normalization",
}

REQUIRED_MEMORY_EXTRACTOR_PROFILE_KEYS = {
    "mode",
    "graph_extraction",
    "entity_types",
    "requires_local_llm",
}

REQUIRED_MEMORY_INDEX_PROFILE_KEYS = {
    "index_kind",
    "backend",
    "embedding_profile",
    "store_safe_text_only",
}

REQUIRED_MEMORY_RANKING_PROFILE_KEYS = {
    "vector_weight",
    "fulltext_weight",
    "graph_weight",
    "fusion",
    "reranker",
    "max_results",
}

REQUIRED_MEMORY_ROUTING_ROOT_KEYS = {
    "version",
    "name",
    "description",
    "sensitivity_levels",
    "default_route",
    "routes",
    "cloud_gate",
}

REQUIRED_MEMORY_ROUTE_KEYS = {
    "default_llm",
    "cloud_allowed",
    "requires_redaction",
}

MEMORY_ROUTE_LLM_VALUES = {
    "local",
    "cloud",
    "deny",
}

MEMORY_SOURCE_KIND_VALUES = {
    "django_model",
    "contract_file",
    "documentation",
    "integration_snapshot",
    "external_api_snapshot",
    "local_path",
    "unc_path",
    "synthetic_fixture",
}

MEMORY_SYNC_MODE_VALUES = {
    "manual",
    "scheduled",
    "incremental",
}

MEMORY_SCOPE_RULE_VALUES = {
    "public_knowledge",
    "authenticated_user",
    "role_scoped",
    "workorder_visibility",
    "inventory_visibility",
    "contract_admin",
    "manual_scope_mapping",
}

MEMORY_SENSITIVITY_VALUES = {
    "public",
    "internal",
    "confidential",
    "pii_redacted",
    "pii_original",
    "secret",
}

MEMORY_PII_POLICY_VALUES = {
    "no_pii_expected",
    "reject_pii",
    "deidentify_before_index",
    "allow_redacted_only",
}

MEMORY_VERSIONING_MODE_VALUES = {
    "snapshot_only",
    "hard_active_soft_raw",
    "append_only",
}

MEMORY_RETENTION_POLICY_VALUES = {
    "default_public",
    "default_internal",
    "short_lived_eval",
    "external_default",
    "short_lived_raw_quarantine",
}

MEMORY_CHUNKING_STRATEGY_VALUES = {
    "field_aware",
    "heading_aware",
    "json_pointer",
}

MEMORY_EXTRACTOR_MODE_VALUES = {
    "text",
    "structured_json",
    "business_event",
    "business_object",
}

MEMORY_INDEX_KIND_VALUES = {
    "vector",
    "fulltext",
    "graph",
}

MEMORY_INDEX_BACKEND_VALUES = {
    "lancedb",
    "qdrant",
    "sqlite_fts",
    "kuzu",
}

MEMORY_RANKING_FUSION_VALUES = {
    "rrf",
    "weighted_sum",
}

MEMORY_RERANKER_VALUES = {
    "none",
    "local_optional",
}

MEMORY_CONTEXT_KIND_VALUES = {
    "question",
    "retrieved_chunk",
    "citation",
    "metadata",
    "graph_fact",
}

MEMORY_ADAPTER_KIND_VALUES = {
    "local_path",
    "unc_path",
    "external_api_snapshot",
}

MEMORY_RAW_MODE_VALUES = {
    "reference_only",
    "quarantine_copy",
    "immutable_raw_vault",
}

MEMORY_ACL_MODE_VALUES = {
    "scope_rule",
    "inherit_source_acl_future",
    "inherit_source_acl",
    "inherit_source_acl_with_fallback",
}

MEMORY_ACL_UNRESOLVED_POLICY_VALUES = {
    "block",
    "admin_only",
    "fallback_scope_rule",
}

MEMORY_PARTIAL_INDEXING_VALUES = {
    "enabled",
    "disabled",
}

MEMORY_INGESTION_ISSUE_KIND_VALUES = {
    "encrypted_file",
    "unsupported_format",
    "file_too_large",
    "partial_indexed",
    "parser_timeout",
    "ocr_timeout",
    "pii_blocked",
    "secret_blocked",
    "acl_unresolved",
    "api_unavailable",
    "rate_limited",
    "malformed_payload",
    "schema_unknown_type",
    "schema_unknown_relation",
    "canonicalization_conflict",
}


def pretty_json(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def load_json_file(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_write_json(path, payload):
    """
    Writes a JSON payload to a file atomically using a temporary file.
    """
    import os
    import tempfile

    data = pretty_json(payload)
    path = Path(path)
    
    # Create temp file in the same directory to ensure os.replace works across devices
    fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(data)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def _ensure_non_empty_mapping(payload, label):
    if not isinstance(payload, dict) or not payload:
        raise ValidationError(f"{label} должна быть непустым JSON-объектом.")


def _ensure_list_of_strings(value, label):
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValidationError(f"{label} должен быть непустым списком строк.")


def _ensure_contract_list(payload, label, required_keys):
    if not isinstance(payload, list):
        raise ValidationError(f"{label} должен быть JSON-массивом.")
    if not payload:
        raise ValidationError(f"{label} должен содержать хотя бы один элемент.")
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"{label} #{index} должен быть JSON-объектом.")
        missing = required_keys - set(item.keys())
        if missing:
            raise ValidationError(
                f"{label} '{item.get('code', index)}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing))}."
            )
        for key in ("code", "title", "owner"):
            if key in required_keys and (not isinstance(item.get(key), str) or not item.get(key)):
                raise ValidationError(f"Поле {key} у {label} '{item.get('code', index)}' должно быть непустой строкой.")


def _ensure_unique_code(item, codes, label):
    code = item.get("code")
    if not isinstance(code, str) or not code:
        raise ValidationError(f"{label} содержит пустой code.")
    if code in codes:
        raise ValidationError(f"{label} '{code}' объявлен повторно.")
    codes.add(code)
    return code


def validate_role_rules_payload(payload, workflow_payload=None):
    _ensure_non_empty_mapping(payload, "Конфигурация ролей")
    known_statuses = set()
    if workflow_payload:
        known_statuses = set(workflow_payload.get("statuses", []))

    for role, config in payload.items():
        if role == "$schema":
            continue
        if not isinstance(config, dict):
            raise ValidationError(f"Роль '{role}' должна быть JSON-объектом.")
        legacy_admin_value = bool(config.get("manage_inventory"))
        for key in BACKWARD_COMPAT_ROLE_DEFAULT_KEYS:
            config.setdefault(key, legacy_admin_value)
        missing = REQUIRED_ROLE_KEYS - set(config.keys())
        if missing:
            raise ValidationError(
                f"Роль '{role}' не содержит обязательные поля: {', '.join(sorted(missing))}."
            )
        for scope_key in (
            "view_scope",
            "edit_scope",
            "comment_scope",
            "upload_attachment_scope",
            "confirm_closure_scope",
            "rate_scope",
            "transition_scope",
        ):
            if config.get(scope_key) not in ROLE_SCOPE_VALUES:
                raise ValidationError(
                    f"У роли '{role}' поле '{scope_key}' содержит недопустимое значение."
                )
        targets = config.get("transition_targets")
        if targets == "*":
            continue
        if not isinstance(targets, list):
            raise ValidationError(
                f"У роли '{role}' поле transition_targets должно быть списком или '*'."
            )
        if known_statuses and set(targets) - known_statuses:
            invalid = ", ".join(sorted(set(targets) - known_statuses))
            raise ValidationError(
                f"У роли '{role}' указаны неизвестные статусы перехода: {invalid}."
            )


def validate_workflow_rules_payload(payload):
    _ensure_non_empty_mapping(payload, "Конфигурация workflow")
    missing = REQUIRED_WORKFLOW_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Конфигурация workflow не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    statuses = payload.get("statuses")
    _ensure_list_of_strings(statuses, "Поле statuses")
    transitions = payload.get("transitions")
    if not isinstance(transitions, dict):
        raise ValidationError("Поле transitions должно быть JSON-объектом.")
    status_set = set(statuses)
    missing_transition_nodes = status_set - set(transitions.keys())
    if missing_transition_nodes:
        raise ValidationError(
            "Для некоторых статусов отсутствует описание переходов: "
            + ", ".join(sorted(missing_transition_nodes))
            + "."
        )
    extra_transition_nodes = set(transitions.keys()) - status_set
    if extra_transition_nodes:
        raise ValidationError(
            "В transitions описаны неизвестные статусы: "
            + ", ".join(sorted(extra_transition_nodes))
            + "."
        )
    for source, targets in transitions.items():
        if not isinstance(targets, list):
            raise ValidationError(f"Статус '{source}' должен содержать список целевых статусов.")
        invalid_targets = set(targets) - status_set
        if invalid_targets:
            raise ValidationError(
                f"У статуса '{source}' указаны неизвестные целевые статусы: "
                + ", ".join(sorted(invalid_targets))
                + "."
            )


def validate_integration_registry_payload(payload):
    if not isinstance(payload, list):
        raise ValidationError("Реестр интеграций должен быть JSON-массивом.")
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"Элемент интеграции #{index} должен быть JSON-объектом.")
        missing = REQUIRED_INTEGRATION_KEYS - set(item.keys())
        if missing:
            raise ValidationError(
                f"Интеграция '{item.get('code', index)}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing))}."
            )
        if not isinstance(item["payloads"], list):
            raise ValidationError(f"Интеграция '{item['code']}' должна содержать список payloads.")


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


def validate_task_brief_payload(payload):
    _ensure_non_empty_mapping(payload, "Task brief")
    missing = REQUIRED_TASK_BRIEF_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Task brief не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for key in ("target_modules", "constraints", "deliverables", "acceptance_checks"):
        if not isinstance(payload.get(key), list):
            raise ValidationError(f"Поле '{key}' в task brief должно быть списком.")


def validate_change_plan_payload(payload):
    _ensure_non_empty_mapping(payload, "Change plan")
    missing = REQUIRED_CHANGE_PLAN_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Change plan не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for key in ("assumptions", "affected_files", "steps", "verification", "risks"):
        if not isinstance(payload.get(key), list):
            raise ValidationError(f"Поле '{key}' в change plan должно быть списком.")


def validate_ai_registry_payload(payload):
    _ensure_non_empty_mapping(payload, "AI registry")
    missing = REQUIRED_AI_REGISTRY_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"AI registry не содержит обязательные поля: {', '.join(sorted(missing))}."
        )


def validate_ai_tools_payload(payload):
    _ensure_non_empty_mapping(payload, "AI tools")
    missing = REQUIRED_AI_TOOLS_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"AI tools registry не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    tools = payload.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ValidationError("AI tools registry должен содержать непустой список tools.")
    for item in tools:
        if not isinstance(item, dict):
            raise ValidationError("Каждый AI tool должен быть JSON-объектом.")
        missing_item_keys = REQUIRED_AI_TOOL_KEYS - set(item.keys())
        if missing_item_keys:
            raise ValidationError(
                f"AI tool '{item.get('id', 'unknown')}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_item_keys))}."
            )
        for key in ("inputs", "outputs"):
            if not isinstance(item.get(key), list):
                raise ValidationError(f"Поле '{key}' у AI tool '{item['id']}' должно быть списком.")
        input_schemas = item.get("input_schemas")
        if input_schemas:
            if not isinstance(input_schemas, dict):
                raise ValidationError(
                    f"AI tool '{item['id']}' field 'input_schemas' must be a JSON object."
                )
            input_names = set(item.get("inputs", []))
            for schema_key in input_schemas:
                if schema_key not in input_names:
                    raise ValidationError(
                        f"AI tool '{item['id']}' has input_schema key '{schema_key}' "
                        f"that is not in its inputs list."
                    )


def validate_ai_task_types_payload(payload):
    _ensure_non_empty_mapping(payload, "AI task types")
    missing = REQUIRED_AI_TASK_TYPES_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"AI task type registry не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    task_types = payload.get("task_types")
    if not isinstance(task_types, list) or not task_types:
        raise ValidationError("AI task type registry должен содержать непустой список task_types.")
    for item in task_types:
        if not isinstance(item, dict):
            raise ValidationError("Каждый AI task type должен быть JSON-объектом.")
        missing_item_keys = REQUIRED_AI_TASK_TYPE_KEYS - set(item.keys())
        if missing_item_keys:
            raise ValidationError(
                f"AI task type '{item.get('id', 'unknown')}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_item_keys))}."
            )
        for key in ("allowed_tools", "example_requests"):
            if not isinstance(item.get(key), list):
                raise ValidationError(f"Поле '{key}' у AI task type '{item['id']}' должно быть списком.")


def validate_memory_sources_payload(payload, profiles_payload=None, routing_payload=None, ingestion_profiles_payload=None):
    if not isinstance(payload, list):
        raise ValidationError("Memory sources должен быть JSON-массивом.")
    if not payload:
        raise ValidationError("Memory sources должен содержать хотя бы один источник.")
    codes = set()
    chunking_profiles = set()
    extractor_profiles = set()
    index_profiles = set()
    if profiles_payload:
        chunking_profiles = set(profiles_payload.get("chunking_profiles", {}).keys())
        extractor_profiles = set(profiles_payload.get("extractor_profiles", {}).keys())
        index_profiles = set(profiles_payload.get("index_profiles", {}).keys())
    sensitivity_levels = set()
    if routing_payload:
        sensitivity_levels = set(routing_payload.get("sensitivity_levels", []))
    ingestion_profile_ids = set()
    if ingestion_profiles_payload:
        ingestion_profile_ids = set(ingestion_profiles_payload.get("profiles", {}).keys())

    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"Memory source #{index} должен быть JSON-объектом.")
        missing = REQUIRED_MEMORY_SOURCE_KEYS - set(item.keys())
        source_code = item.get("code", index)
        if missing:
            raise ValidationError(
                f"Memory source '{source_code}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing))}."
            )
        code = item["code"]
        if not isinstance(code, str) or not code:
            raise ValidationError(f"Memory source #{index} содержит пустой code.")
        if code in codes:
            raise ValidationError(f"Memory source '{code}' объявлен повторно.")
        codes.add(code)
        for key in (
            "title",
            "description",
            "domain",
            "owner",
            "extractor_profile",
            "chunking_profile",
        ):
            if not isinstance(item.get(key), str) or not item.get(key):
                raise ValidationError(f"Поле '{key}' у memory source '{code}' должно быть непустой строкой.")
        source_ref = item.get("source_ref")
        if not isinstance(source_ref, str) or not source_ref:
            raise ValidationError(f"Поле 'source_ref' у memory source '{code}' должно быть непустой строкой.")
        if not isinstance(item.get("enabled"), bool):
            raise ValidationError(f"Поле 'enabled' у memory source '{code}' должно быть boolean.")
        schedule = item.get("schedule")
        if schedule is not None and not isinstance(schedule, str):
            raise ValidationError(f"Поле 'schedule' у memory source '{code}' должно быть строкой или null.")
        enum_checks = (
            ("source_kind", MEMORY_SOURCE_KIND_VALUES),
            ("sync_mode", MEMORY_SYNC_MODE_VALUES),
            ("scope_rule", MEMORY_SCOPE_RULE_VALUES),
            ("sensitivity", MEMORY_SENSITIVITY_VALUES),
            ("pii_policy", MEMORY_PII_POLICY_VALUES),
            ("versioning_mode", MEMORY_VERSIONING_MODE_VALUES),
            ("retention_policy", MEMORY_RETENTION_POLICY_VALUES),
        )
        for key, allowed_values in enum_checks:
            if item.get(key) not in allowed_values:
                raise ValidationError(f"Memory source '{code}' содержит недопустимое значение поля '{key}'.")
        _ensure_list_of_strings(item.get("index_profiles"), f"Поле index_profiles у memory source '{code}'")
        if len(item["index_profiles"]) != len(set(item["index_profiles"])):
            raise ValidationError(f"Поле index_profiles у memory source '{code}' содержит дубликаты.")
        ignore_patterns = item.get("ignore_patterns", [])
        if not isinstance(ignore_patterns, list) or not all(isinstance(pattern, str) for pattern in ignore_patterns):
            raise ValidationError(f"Поле 'ignore_patterns' у memory source '{code}' должно быть списком строк.")
        ingestion_profile = item.get("ingestion_profile")
        if ingestion_profile is not None:
            if not isinstance(ingestion_profile, str) or not ingestion_profile:
                raise ValidationError(f"Поле 'ingestion_profile' у memory source '{code}' должно быть непустой строкой.")
            if ingestion_profile_ids and ingestion_profile not in ingestion_profile_ids:
                raise ValidationError(
                    f"Memory source '{code}' ссылается на неизвестный ingestion_profile "
                    f"'{ingestion_profile}'."
                )
        external_connector = item.get("external_connector")
        if external_connector is not None:
            if not isinstance(external_connector, dict):
                raise ValidationError(f"Поле 'external_connector' у memory source '{code}' должно быть JSON-объектом.")
            if item.get("source_kind") != "external_api_snapshot":
                raise ValidationError(
                    f"Поле 'external_connector' допустимо только для source_kind external_api_snapshot у memory source '{code}'."
                )
            queue_backend = external_connector.get("queue_backend")
            if queue_backend != "sqlite":
                raise ValidationError(f"Memory source '{code}' должен использовать queue_backend 'sqlite' в MVP.")
            raw_mode = external_connector.get("raw_mode")
            if raw_mode not in {"normalized_only", "metadata_only", "short_lived_raw_quarantine"}:
                raise ValidationError(f"Memory source '{code}' содержит недопустимый external_connector.raw_mode.")
            scope_mapping = external_connector.get("scope_mapping")
            if scope_mapping != "manual":
                raise ValidationError(f"Memory source '{code}' должен использовать external_connector.scope_mapping 'manual'.")
        if chunking_profiles and item["chunking_profile"] not in chunking_profiles:
            raise ValidationError(
                f"Memory source '{code}' ссылается на неизвестный chunking_profile "
                f"'{item['chunking_profile']}'."
            )
        if extractor_profiles and item["extractor_profile"] not in extractor_profiles:
            raise ValidationError(
                f"Memory source '{code}' ссылается на неизвестный extractor_profile "
                f"'{item['extractor_profile']}'."
            )
        if index_profiles:
            unknown_index_profiles = set(item["index_profiles"]) - index_profiles
            if unknown_index_profiles:
                raise ValidationError(
                    f"Memory source '{code}' ссылается на неизвестные index_profiles: "
                    + ", ".join(sorted(unknown_index_profiles))
                    + "."
                )
        if sensitivity_levels and item["sensitivity"] not in sensitivity_levels:
            raise ValidationError(
                f"Memory source '{code}' ссылается на неизвестный sensitivity "
                f"'{item['sensitivity']}'."
            )


def validate_memory_ingestion_profiles_payload(payload):
    _ensure_non_empty_mapping(payload, "Memory ingestion profiles")
    missing = REQUIRED_MEMORY_INGESTION_PROFILES_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Memory ingestion profiles не содержит обязательные поля: {', '.join(sorted(missing))}."
        )

    for root_key in ("adapter_profiles", "parser_profiles", "ocr_profiles", "limit_profiles", "profiles"):
        if not isinstance(payload.get(root_key), dict) or not payload.get(root_key):
            raise ValidationError(f"Поле '{root_key}' в memory ingestion profiles должно быть непустым JSON-объектом.")

    for profile_id, profile in payload["adapter_profiles"].items():
        if not isinstance(profile, dict):
            raise ValidationError(f"Adapter profile '{profile_id}' должен быть JSON-объектом.")
        if profile.get("adapter_kind") not in MEMORY_ADAPTER_KIND_VALUES:
            raise ValidationError(f"Adapter profile '{profile_id}' содержит недопустимый adapter_kind.")
        if not isinstance(profile.get("follow_symlinks", False), bool):
            raise ValidationError(f"Поле follow_symlinks у adapter profile '{profile_id}' должно быть boolean.")

    for profile_id, profile in payload["parser_profiles"].items():
        if not isinstance(profile, dict):
            raise ValidationError(f"Parser profile '{profile_id}' должен быть JSON-объектом.")
        cascade = profile.get("cascade")
        _ensure_list_of_strings(cascade, f"Поле cascade у parser profile '{profile_id}'")
        if not cascade:
            raise ValidationError(f"Поле cascade у parser profile '{profile_id}' должно быть непустым списком.")
        supported_extensions = profile.get("supported_extensions")
        _ensure_list_of_strings(supported_extensions, f"Поле supported_extensions у parser profile '{profile_id}'")
        if not isinstance(profile.get("extract_embedded_images", False), bool):
            raise ValidationError(
                f"Поле extract_embedded_images у parser profile '{profile_id}' должно быть boolean."
            )

    for profile_id, profile in payload["ocr_profiles"].items():
        if not isinstance(profile, dict):
            raise ValidationError(f"OCR profile '{profile_id}' должен быть JSON-объектом.")
        if not isinstance(profile.get("enabled"), bool):
            raise ValidationError(f"Поле enabled у OCR profile '{profile_id}' должно быть boolean.")
        _ensure_list_of_strings(profile.get("languages"), f"Поле languages у OCR profile '{profile_id}'")
        backend = profile.get("backend")
        if not isinstance(backend, str) or not backend:
            raise ValidationError(f"Поле backend у OCR profile '{profile_id}' должно быть непустой строкой.")
        cloud_policy = profile.get("cloud_policy", "deny")
        if cloud_policy not in {"deny", "prepared_package_only"}:
            raise ValidationError(f"OCR profile '{profile_id}' содержит недопустимый cloud_policy.")

    for profile_id, profile in payload["limit_profiles"].items():
        if not isinstance(profile, dict):
            raise ValidationError(f"Limit profile '{profile_id}' должен быть JSON-объектом.")
        max_file_size_mb = profile.get("max_file_size_mb")
        if type(max_file_size_mb) is not int or max_file_size_mb <= 0:
            raise ValidationError(f"Поле max_file_size_mb у limit profile '{profile_id}' должно быть положительным числом.")
        for key in ("parser_timeout_seconds", "ocr_timeout_seconds"):
            value = profile.get(key)
            if type(value) is not int or value <= 0:
                raise ValidationError(f"Поле {key} у limit profile '{profile_id}' должно быть положительным числом.")

    adapter_ids = set(payload["adapter_profiles"].keys())
    parser_ids = set(payload["parser_profiles"].keys())
    ocr_ids = set(payload["ocr_profiles"].keys())
    limit_ids = set(payload["limit_profiles"].keys())
    for profile_id, profile in payload["profiles"].items():
        if not isinstance(profile, dict):
            raise ValidationError(f"Ingestion profile '{profile_id}' должен быть JSON-объектом.")
        missing_profile_keys = REQUIRED_MEMORY_INGESTION_PROFILE_KEYS - set(profile.keys())
        if missing_profile_keys:
            raise ValidationError(
                f"Ingestion profile '{profile_id}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_profile_keys))}."
            )
        if profile.get("adapter_profile") not in adapter_ids:
            raise ValidationError(f"Ingestion profile '{profile_id}' ссылается на неизвестный adapter_profile.")
        if profile.get("parser_profile") not in parser_ids:
            raise ValidationError(f"Ingestion profile '{profile_id}' ссылается на неизвестный parser_profile.")
        if profile.get("ocr_profile") not in ocr_ids:
            raise ValidationError(f"Ingestion profile '{profile_id}' ссылается на неизвестный ocr_profile.")
        if profile.get("limit_profile") not in limit_ids:
            raise ValidationError(f"Ingestion profile '{profile_id}' ссылается на неизвестный limit_profile.")
        if profile.get("raw_mode") not in MEMORY_RAW_MODE_VALUES:
            raise ValidationError(f"Ingestion profile '{profile_id}' содержит недопустимый raw_mode.")
        if profile.get("acl_mode") not in MEMORY_ACL_MODE_VALUES:
            raise ValidationError(f"Ingestion profile '{profile_id}' содержит недопустимый acl_mode.")
        acl_policy = profile.get("acl_policy", {})
        if acl_policy:
            if not isinstance(acl_policy, dict):
                raise ValidationError(f"Поле acl_policy у ingestion profile '{profile_id}' должно быть JSON-объектом.")
            unresolved_policy = acl_policy.get("unresolved_policy", "block")
            if unresolved_policy not in MEMORY_ACL_UNRESOLVED_POLICY_VALUES:
                raise ValidationError(
                    f"Ingestion profile '{profile_id}' содержит недопустимый acl_policy.unresolved_policy."
                )
            if not isinstance(acl_policy.get("fail_closed", True), bool):
                raise ValidationError(
                    f"Поле acl_policy.fail_closed у ingestion profile '{profile_id}' должно быть boolean."
                )
        if profile.get("partial_indexing") not in MEMORY_PARTIAL_INDEXING_VALUES:
            raise ValidationError(f"Ingestion profile '{profile_id}' содержит недопустимый partial_indexing.")
        issue_policy = profile.get("issue_policy")
        if not isinstance(issue_policy, dict):
            raise ValidationError(f"Поле issue_policy у ingestion profile '{profile_id}' должно быть JSON-объектом.")
        create_issue_kinds = issue_policy.get("create_issue_kinds")
        _ensure_list_of_strings(create_issue_kinds, f"Поле create_issue_kinds у ingestion profile '{profile_id}'")
        unknown_issue_kinds = set(create_issue_kinds) - MEMORY_INGESTION_ISSUE_KIND_VALUES
        if unknown_issue_kinds:
            raise ValidationError(
                f"Ingestion profile '{profile_id}' содержит неизвестные issue kinds: "
                + ", ".join(sorted(unknown_issue_kinds))
                + "."
            )


def validate_memory_graph_schema_payload(payload):
    _ensure_non_empty_mapping(payload, "Memory graph schema")
    missing = REQUIRED_MEMORY_GRAPH_SCHEMA_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Memory graph schema не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for key in ("schema_version", "name", "description"):
        if not isinstance(payload.get(key), str) or not payload.get(key):
            raise ValidationError(f"Поле '{key}' в memory graph schema должно быть непустой строкой.")

    entity_types = payload.get("entity_types")
    relation_types = payload.get("relation_types")
    attribute_types = payload.get("attribute_types")
    if not isinstance(entity_types, dict) or not entity_types:
        raise ValidationError("Поле entity_types в memory graph schema должно быть непустым JSON-объектом.")
    if not isinstance(relation_types, dict):
        raise ValidationError("Поле relation_types в memory graph schema должно быть JSON-объектом.")
    if not isinstance(attribute_types, dict):
        raise ValidationError("Поле attribute_types в memory graph schema должно быть JSON-объектом.")

    entity_codes = set(entity_types.keys())
    for code, item in entity_types.items():
        if not isinstance(item, dict):
            raise ValidationError(f"Entity type '{code}' должен быть JSON-объектом.")
        for key in ("label", "description", "status"):
            if not isinstance(item.get(key), str) or not item.get(key):
                raise ValidationError(f"Поле '{key}' у entity type '{code}' должно быть непустой строкой.")
        if item["status"] not in {"proposed", "accepted", "rejected", "deprecated"}:
            raise ValidationError(f"Entity type '{code}' содержит недопустимый status.")
        _ensure_list_of_strings(item.get("positive_examples", []), f"Поле positive_examples у entity type '{code}'")
        _ensure_list_of_strings(item.get("negative_examples", []), f"Поле negative_examples у entity type '{code}'")
        _ensure_list_of_strings(item.get("attributes", []), f"Поле attributes у entity type '{code}'")

    for code, item in relation_types.items():
        if not isinstance(item, dict):
            raise ValidationError(f"Relation type '{code}' должен быть JSON-объектом.")
        for key in ("label", "description", "subject_type", "object_type", "status"):
            if not isinstance(item.get(key), str) or not item.get(key):
                raise ValidationError(f"Поле '{key}' у relation type '{code}' должно быть непустой строкой.")
        if item["subject_type"] not in entity_codes:
            raise ValidationError(f"Relation type '{code}' ссылается на неизвестный subject_type.")
        if item["object_type"] not in entity_codes:
            raise ValidationError(f"Relation type '{code}' ссылается на неизвестный object_type.")
        if item["status"] not in {"proposed", "accepted", "rejected", "deprecated"}:
            raise ValidationError(f"Relation type '{code}' содержит недопустимый status.")

    for key in ("canonicalization_rules", "negative_examples", "forbidden_patterns", "department_evidence", "changelog"):
        if not isinstance(payload.get(key), list):
            raise ValidationError(f"Поле {key} в memory graph schema должно быть списком.")
    for key in ("confidence_thresholds", "auto_accept_policy", "review_policy"):
        if not isinstance(payload.get(key), dict):
            raise ValidationError(f"Поле {key} в memory graph schema должно быть JSON-объектом.")


def validate_memory_profiles_payload(payload):
    _ensure_non_empty_mapping(payload, "Memory profiles")
    missing = REQUIRED_MEMORY_PROFILES_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Memory profiles не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for root_key in REQUIRED_MEMORY_PROFILES_ROOT_KEYS:
        if not isinstance(payload.get(root_key), dict) or not payload.get(root_key):
            raise ValidationError(f"Поле '{root_key}' в memory profiles должно быть непустым JSON-объектом.")

    for profile_id, profile in payload["chunking_profiles"].items():
        if not isinstance(profile, dict):
            raise ValidationError(f"Chunking profile '{profile_id}' должен быть JSON-объектом.")
        missing_profile_keys = REQUIRED_MEMORY_CHUNKING_PROFILE_KEYS - set(profile.keys())
        if missing_profile_keys:
            raise ValidationError(
                f"Chunking profile '{profile_id}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_profile_keys))}."
            )
        for key in ("max_tokens", "overlap_tokens"):
            if type(profile.get(key)) is not int or profile[key] < 0:
                raise ValidationError(f"Поле '{key}' у chunking profile '{profile_id}' должно быть неотрицательным числом.")
        if profile["max_tokens"] <= 0:
            raise ValidationError(f"Поле 'max_tokens' у chunking profile '{profile_id}' должно быть больше 0.")
        if profile["overlap_tokens"] >= profile["max_tokens"]:
            raise ValidationError(
                f"Поле 'overlap_tokens' у chunking profile '{profile_id}' должно быть меньше max_tokens."
            )
        if profile.get("strategy") not in MEMORY_CHUNKING_STRATEGY_VALUES:
            raise ValidationError(f"Chunking profile '{profile_id}' содержит недопустимую strategy.")
        _ensure_list_of_strings(profile.get("preserve_fields"), f"Поле preserve_fields у chunking profile '{profile_id}'")

    for profile_id, profile in payload["extractor_profiles"].items():
        if not isinstance(profile, dict):
            raise ValidationError(f"Extractor profile '{profile_id}' должен быть JSON-объектом.")
        missing_profile_keys = REQUIRED_MEMORY_EXTRACTOR_PROFILE_KEYS - set(profile.keys())
        if missing_profile_keys:
            raise ValidationError(
                f"Extractor profile '{profile_id}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_profile_keys))}."
            )
        if profile.get("mode") not in MEMORY_EXTRACTOR_MODE_VALUES:
            raise ValidationError(f"Extractor profile '{profile_id}' содержит недопустимый mode.")
        if not isinstance(profile.get("graph_extraction"), bool):
            raise ValidationError(f"Поле 'graph_extraction' у extractor profile '{profile_id}' должно быть boolean.")
        _ensure_list_of_strings(profile.get("entity_types"), f"Поле entity_types у extractor profile '{profile_id}'")
        if not isinstance(profile.get("requires_local_llm"), bool):
            raise ValidationError(f"Поле 'requires_local_llm' у extractor profile '{profile_id}' должно быть boolean.")

    for profile_id, profile in payload["embedding_profiles"].items():
        if not isinstance(profile, dict):
            raise ValidationError(f"Embedding profile '{profile_id}' должен быть JSON-объектом.")
        missing_profile_keys = REQUIRED_MEMORY_EMBEDDING_PROFILE_KEYS - set(profile.keys())
        if missing_profile_keys:
            raise ValidationError(
                f"Embedding profile '{profile_id}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_profile_keys))}."
            )
        for key in ("provider", "model"):
            if not isinstance(profile.get(key), str) or not profile.get(key):
                raise ValidationError(f"Поле '{key}' у embedding profile '{profile_id}' должно быть непустой строкой.")
        if type(profile.get("dimensions")) is not int or profile["dimensions"] <= 0:
            raise ValidationError(f"Поле 'dimensions' у embedding profile '{profile_id}' должно быть положительным числом.")
        if not isinstance(profile.get("normalization"), bool):
            raise ValidationError(f"Поле 'normalization' у embedding profile '{profile_id}' должно быть boolean.")
        if profile.get("provider") != "local":
            raise ValidationError(f"Embedding profile '{profile_id}' содержит недопустимый provider.")

    embedding_profile_ids = set(payload["embedding_profiles"].keys())
    for profile_id, profile in payload["index_profiles"].items():
        if not isinstance(profile, dict):
            raise ValidationError(f"Index profile '{profile_id}' должен быть JSON-объектом.")
        missing_profile_keys = REQUIRED_MEMORY_INDEX_PROFILE_KEYS - set(profile.keys())
        if missing_profile_keys:
            raise ValidationError(
                f"Index profile '{profile_id}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_profile_keys))}."
            )
        if profile.get("index_kind") not in MEMORY_INDEX_KIND_VALUES:
            raise ValidationError(f"Index profile '{profile_id}' содержит недопустимый index_kind.")
        if profile.get("backend") not in MEMORY_INDEX_BACKEND_VALUES:
            raise ValidationError(f"Index profile '{profile_id}' содержит недопустимый backend.")
        embedding_profile = profile.get("embedding_profile")
        if embedding_profile is not None and embedding_profile not in embedding_profile_ids:
            raise ValidationError(
                f"Index profile '{profile_id}' ссылается на неизвестный embedding_profile '{embedding_profile}'."
            )
        if profile["index_kind"] == "vector" and not embedding_profile:
            raise ValidationError(f"Vector index profile '{profile_id}' должен ссылаться на embedding_profile.")
        if profile["index_kind"] != "vector" and embedding_profile is not None:
            raise ValidationError(f"Non-vector index profile '{profile_id}' не должен ссылаться на embedding_profile.")
        if not isinstance(profile.get("store_safe_text_only"), bool):
            raise ValidationError(f"Поле 'store_safe_text_only' у index profile '{profile_id}' должно быть boolean.")

    for profile_id, profile in payload["ranking_profiles"].items():
        if not isinstance(profile, dict):
            raise ValidationError(f"Ranking profile '{profile_id}' должен быть JSON-объектом.")
        missing_profile_keys = REQUIRED_MEMORY_RANKING_PROFILE_KEYS - set(profile.keys())
        if missing_profile_keys:
            raise ValidationError(
                f"Ranking profile '{profile_id}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_profile_keys))}."
            )
        for key in ("vector_weight", "fulltext_weight", "graph_weight"):
            if type(profile.get(key)) not in (int, float) or profile[key] < 0 or profile[key] > 1:
                raise ValidationError(
                    f"Поле '{key}' у ranking profile '{profile_id}' должно быть числом от 0 до 1."
                )
        if profile.get("fusion") not in MEMORY_RANKING_FUSION_VALUES:
            raise ValidationError(f"Ranking profile '{profile_id}' содержит недопустимый fusion.")
        if profile.get("reranker") not in MEMORY_RERANKER_VALUES:
            raise ValidationError(f"Ranking profile '{profile_id}' содержит недопустимый reranker.")
        if type(profile.get("max_results")) is not int or profile["max_results"] <= 0:
            raise ValidationError(f"Поле 'max_results' у ranking profile '{profile_id}' должно быть положительным числом.")


def validate_memory_routing_payload(payload):
    _ensure_non_empty_mapping(payload, "Memory routing")
    missing = REQUIRED_MEMORY_ROUTING_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Memory routing не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    sensitivity_levels = payload.get("sensitivity_levels")
    _ensure_list_of_strings(sensitivity_levels, "Поле sensitivity_levels")
    if len(sensitivity_levels) != len(set(sensitivity_levels)):
        raise ValidationError("Поле sensitivity_levels в memory routing содержит дубликаты.")
    invalid_sensitivity_levels = set(sensitivity_levels) - MEMORY_SENSITIVITY_VALUES
    if invalid_sensitivity_levels:
        raise ValidationError(
            "Memory routing содержит неизвестные sensitivity levels: "
            + ", ".join(sorted(invalid_sensitivity_levels))
            + "."
        )
    if payload.get("default_route") not in sensitivity_levels:
        raise ValidationError("Поле default_route в memory routing должно ссылаться на sensitivity_levels.")
    routes = payload.get("routes")
    if not isinstance(routes, dict) or not routes:
        raise ValidationError("Поле routes в memory routing должно быть непустым JSON-объектом.")
    missing_routes = set(sensitivity_levels) - set(routes.keys())
    if missing_routes:
        raise ValidationError(
            "В memory routing отсутствуют routes для sensitivity levels: "
            + ", ".join(sorted(missing_routes))
            + "."
        )
    extra_routes = set(routes.keys()) - set(sensitivity_levels)
    if extra_routes:
        raise ValidationError(
            "В memory routing объявлены routes для неизвестных sensitivity levels: "
            + ", ".join(sorted(extra_routes))
            + "."
        )
    for level, route in routes.items():
        if not isinstance(route, dict):
            raise ValidationError(f"Route '{level}' в memory routing должен быть JSON-объектом.")
        missing_route_keys = REQUIRED_MEMORY_ROUTE_KEYS - set(route.keys())
        if missing_route_keys:
            raise ValidationError(
                f"Route '{level}' в memory routing не содержит обязательные поля: "
                f"{', '.join(sorted(missing_route_keys))}."
            )
        if route.get("default_llm") not in MEMORY_ROUTE_LLM_VALUES:
            raise ValidationError(f"Route '{level}' содержит недопустимый default_llm.")
        for key in ("cloud_allowed", "requires_redaction"):
            if not isinstance(route.get(key), bool):
                raise ValidationError(f"Поле '{key}' у route '{level}' должно быть boolean.")
        if not isinstance(route.get("allow_original_pii"), bool):
            raise ValidationError(f"Поле 'allow_original_pii' у route '{level}' должно быть boolean.")
        context_kinds = route.get("allowed_context_kinds")
        if not isinstance(context_kinds, list) or not all(kind in MEMORY_CONTEXT_KIND_VALUES for kind in context_kinds):
            raise ValidationError(f"Поле 'allowed_context_kinds' у route '{level}' содержит недопустимые значения.")
        if len(context_kinds) != len(set(context_kinds)):
            raise ValidationError(f"Поле 'allowed_context_kinds' у route '{level}' содержит дубликаты.")
        denial_reason = route.get("denial_reason")
        if denial_reason is not None and not isinstance(denial_reason, str):
            raise ValidationError(f"Поле 'denial_reason' у route '{level}' должно быть строкой или null.")
        if level in {"pii_original", "secret"} and route.get("cloud_allowed"):
            raise ValidationError(f"Route '{level}' не должен разрешать cloud_allowed.")
        if level == "pii_original" and route.get("allow_original_pii"):
            raise ValidationError("Route 'pii_original' не должен разрешать allow_original_pii.")
        if level == "secret" and route.get("default_llm") != "deny":
            raise ValidationError("Route 'secret' должен иметь default_llm='deny'.")
        if level == "secret" and context_kinds:
            raise ValidationError("Route 'secret' не должен разрешать allowed_context_kinds.")

    cloud_gate = payload.get("cloud_gate")
    if not isinstance(cloud_gate, dict):
        raise ValidationError("Поле cloud_gate в memory routing должно быть JSON-объектом.")
    if cloud_gate.get("mode") != "explicit_allow":
        raise ValidationError("Поле cloud_gate.mode должно быть explicit_allow.")
    if cloud_gate.get("max_sensitivity") not in {"public", "internal"}:
        raise ValidationError("Поле cloud_gate.max_sensitivity должно быть public или internal.")
    if not isinstance(cloud_gate.get("requires_redaction"), bool):
        raise ValidationError("Поле cloud_gate.requires_redaction должно быть boolean.")
    forbidden = cloud_gate.get("forbidden_sensitivities")
    if not isinstance(forbidden, list) or not forbidden:
        raise ValidationError("Поле cloud_gate.forbidden_sensitivities должно быть непустым списком.")
    forbidden_set = set(forbidden)
    if len(forbidden) != len(forbidden_set):
        raise ValidationError("Поле cloud_gate.forbidden_sensitivities содержит дубликаты.")
    if forbidden_set - set(sensitivity_levels):
        raise ValidationError("Поле cloud_gate.forbidden_sensitivities ссылается на неизвестные sensitivity levels.")
    unsafe_cloud_allowed = {
        level for level, route in routes.items()
        if level in forbidden_set and route.get("cloud_allowed")
    }
    if unsafe_cloud_allowed:
        raise ValidationError(
            "Cloud gate запрещает sensitivity levels, но routes разрешают cloud_allowed: "
            + ", ".join(sorted(unsafe_cloud_allowed))
            + "."
        )


def validate_ai_tools_drift(json_payload, canonical_tools):
    canonical_by_id = {tool["id"]: tool for tool in canonical_tools}
    json_by_id = {tool["id"]: tool for tool in json_payload.get("tools", [])}

    for tool_id, canonical_tool in canonical_by_id.items():
        if tool_id not in json_by_id:
            raise ValidationError(f"Tool '{tool_id}' is missing in JSON registry.")
        json_tool = json_by_id[tool_id]

        for key in REQUIRED_AI_TOOL_KEYS:
            if canonical_tool.get(key) != json_tool.get(key):
                raise ValidationError(
                    f"Tool '{tool_id}' field '{key}' differs: canonical={canonical_tool.get(key)!r}, json={json_tool.get(key)!r}."
                )


def validate_ai_task_types_tool_alignment(task_types_payload, tools_payload):
    """
    Validate that every tool referenced in task_types[].allowed_tools exists
    in the tool catalog.

    This catches drift where a task type declares a tool that was removed or
    renamed in the tool catalog — before runtime.
    """
    tool_ids_in_catalog = {tool["id"] for tool in tools_payload.get("tools", [])}
    task_types = task_types_payload.get("task_types", [])
    for task_type in task_types:
        tt_id = task_type.get("id", "unknown")
        for tool_id in task_type.get("allowed_tools", []):
            if tool_id not in tool_ids_in_catalog:
                raise ValidationError(
                    f"Task type '{tt_id}' declares allowed_tool '{tool_id}' "
                    f"which does not exist in the tool catalog."
                )


def validate_ai_write_confirmation_alignment(task_types_payload, tools_payload):
    """
    Validate that write-mode task types and their write-mode tools have
    aligned requires_confirmation semantics.

    If a write tool declares requires_confirmation=True, all task types that
    use it exclusively for write operations should also require confirmation.
    This catches misalignment between tool-level and task-type-level policy.
    """
    tool_by_id = {tool["id"]: tool for tool in tools_payload.get("tools", [])}
    task_types = task_types_payload.get("task_types", [])

    for task_type in task_types:
        tt_id = task_type.get("id", "unknown")
        mode = task_type.get("mode", "")
        tt_requires_confirmation = task_type.get("requires_confirmation", False)

        if mode != "write":
            continue

        for tool_id in task_type.get("allowed_tools", []):
            tool = tool_by_id.get(tool_id, {})
            if tool.get("mode") != "write":
                continue
            tool_requires_confirmation = tool.get("requires_confirmation", False)
            if tool_requires_confirmation != tt_requires_confirmation:
                raise ValidationError(
                    f"Task type '{tt_id}' (mode=write) has requires_confirmation={tt_requires_confirmation} "
                    f"but its write tool '{tool_id}' has requires_confirmation={tool_requires_confirmation}. "
                    f"These must be aligned for write-mode task types."
                )


def validate_ai_task_types_slot_coverage(task_types_payload):
    """
    Validate that within each task type, required_slots and optional_slots
    are disjoint sets (a slot cannot be both required and optional).

    Also validates that required_slots does not contain duplicates.
    """
    task_types = task_types_payload.get("task_types", [])
    for task_type in task_types:
        tt_id = task_type.get("id", "unknown")
        required = set(task_type.get("required_slots", []))
        optional = set(task_type.get("optional_slots", []))

        overlap = required & optional
        if overlap:
            raise ValidationError(
                f"Task type '{tt_id}' has slots that are both required and optional: "
                f"{sorted(overlap)}. Required and optional slot sets must be disjoint."
            )

        if len(required) != len(task_type.get("required_slots", [])):
            raise ValidationError(
                f"Task type '{tt_id}' has duplicate entries in required_slots."
            )


# Minimum identity fields the runtime request identity model must carry, per
# the identity_model contract in contracts/ai/registry.json.
IDENTITY_MINIMUM_FIELDS = frozenset({
    "user_id",
    "roles",
    "session_id",
    "conversation_id",
    "request_id",
})


def validate_ai_identity_model_alignment(registry_payload):
    """
    Validate that the identity_model.minimum_fields declared in the AI registry
    include all fields required by the runtime request identity model.

    The Django chat surface and gateway client must carry: user_id, roles,
    session_id, conversation_id, request_id.  Any missing field is a
    contract violation that breaks trace correlation.
    """
    identity_model = registry_payload.get("identity_model", {})
    minimum_fields = set(identity_model.get("minimum_fields", []))
    missing = IDENTITY_MINIMUM_FIELDS - minimum_fields
    if missing:
        raise ValidationError(
            f"AI registry identity_model.minimum_fields is missing required fields: "
            f"{', '.join(sorted(missing))}. "
            f"The runtime request identity model must carry these to enable trace correlation."
        )
