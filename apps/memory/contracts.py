"""Валидаторы доменных контрактов памяти (sources, profiles, routing, trust и др.).

Содержит правила предметной области AI memory service: реестр источников,
профили ingestion/chunking/index/ranking, routing по чувствительности, trust- и
claims-политики, retrieval budget, graph schema и профили автоупорядочивания
файлов. По правилам 3 и 5 AGENTS.md эти доменные правила живут в приложении
``apps.memory``, а не в ядре.

Универсальные JSON-примитивы (``_ensure_*``) импортируются из
``apps.core.json_utils`` (обратной зависимости нет).
"""
import re

from django.core.exceptions import ValidationError

from apps.core.json_utils import (
    _ensure_list_of_strings,
    _ensure_non_empty_mapping,
    _ensure_number,
    _ensure_positive_int,
)


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

OPTIONAL_MEMORY_SOURCE_TRUST_KEYS = {
    "trust_status",
    "authority_class",
    "trusted_for_context",
    "requires_source_review",
    "review_owner",
    "trusted_context_kinds",
    "untrusted_handling",
}

OPTIONAL_MEMORY_SOURCE_POLICY_KEYS = {
    "source_origin",
    "privacy_profile",
    "access_policy",
}

REQUIRED_MEMORY_TRUST_POLICY_ROOT_KEYS = {
    "version",
    "name",
    "description",
    "trust_statuses",
    "authority_classes",
    "defaults_by_source_kind",
    "direct_context_policy",
    "review_roles",
}

REQUIRED_MEMORY_CLAIMS_POLICY_ROOT_KEYS = {
    "version",
    "name",
    "description",
    "claim_types",
    "claim_statuses",
    "belief_statuses",
    "review_rules",
    "freshness_windows",
    "contradiction_policy",
}

REQUIRED_MEMORY_RETRIEVAL_BUDGET_ROOT_KEYS = {
    "version",
    "name",
    "description",
    "hot_path",
    "rank_fusion",
    "context_packing",
    "optional_llm_rerank",
    "background_batches",
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

REQUIRED_MEMORY_FILE_ORGANIZATION_ROOT_KEYS = {
    "version",
    "name",
    "description",
    "profiles",
}

REQUIRED_MEMORY_FILE_ORGANIZATION_PROFILE_KEYS = {
    "enabled",
    "source_code",
    "incoming_path",
    "managed_root",
    "baseline_profile",
    "physical_move_policy",
    "source_delete_policy",
    "storage_backend",
    "future_backends",
    "proposal_thresholds",
}

REQUIRED_MEMORY_FILE_SOURCE_DELETE_POLICY_KEYS = {
    "mode",
    "retention_days",
    "requires_backup_checkpoint",
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
    "pii_off",
    "pii_guarded",
    "pii_strict",
}

MEMORY_PRIVACY_PROFILE_VALUES = {
    "pii_off",
    "pii_guarded",
    "pii_strict",
}

MEMORY_SOURCE_ORIGIN_VALUES = {
    "internal",
    "external",
}

MEMORY_ACCESS_POLICY_MODE_VALUES = {
    "scope_tokens",
    "acl_inherited",
    "manual_mapping",
    "adapter_check",
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
    "claim",
    "belief",
}

MEMORY_TRUST_STATUS_VALUES = {
    "trusted",
    "review_required",
    "candidate_only",
    "quarantined",
    "blocked",
}

MEMORY_AUTHORITY_CLASS_VALUES = {
    "system_of_record",
    "approved_corpus",
    "approved_user_memory",
    "reviewed_org_knowledge",
    "external_observation",
    "candidate_input",
}

MEMORY_UNTRUSTED_HANDLING_VALUES = {
    "review_required",
    "candidate_only",
    "quarantine",
    "block",
    "blocked",
}

MEMORY_CLAIM_TYPE_VALUES = {
    "fact",
    "preference",
    "procedure",
    "policy",
    "decision",
    "metric_observation",
    "incident",
    "action_outcome",
}

MEMORY_CLAIM_STATUS_VALUES = {
    "candidate",
    "accepted",
    "rejected",
    "contested",
    "superseded",
    "expired",
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
    "pii_audit",
    "secret_blocked",
    "acl_unresolved",
    "api_unavailable",
    "rate_limited",
    "malformed_payload",
    "schema_unknown_type",
    "schema_unknown_relation",
    "canonicalization_conflict",
}

MEMORY_FILE_ORGANIZATION_STORAGE_BACKEND_VALUES = {
    "managed_fs",
    "s3_compatible",
}

MEMORY_FILE_ORGANIZATION_PHYSICAL_MOVE_POLICY_VALUES = {
    "approval_required",
    "disabled",
}

MEMORY_FILE_ORGANIZATION_DELETE_MODE_VALUES = {
    "quarantine_then_purge",
    "quarantine_only",
    "disabled",
}


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
        _validate_memory_source_trust_fields(item, source_code=code)
        _validate_memory_source_policy_fields(item, source_code=code)
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


def validate_memory_trust_policy_payload(payload):
    _ensure_non_empty_mapping(payload, "Memory trust policy")
    missing = REQUIRED_MEMORY_TRUST_POLICY_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Memory trust policy не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for key in ("version", "name", "description"):
        if not isinstance(payload.get(key), str) or not payload.get(key):
            raise ValidationError(f"Поле '{key}' в memory trust policy должно быть непустой строкой.")
    _ensure_list_of_strings(payload.get("trust_statuses"), "Поле trust_statuses в memory trust policy")
    unknown_statuses = set(payload["trust_statuses"]) - MEMORY_TRUST_STATUS_VALUES
    if unknown_statuses:
        raise ValidationError(
            "Memory trust policy содержит неизвестные trust_statuses: "
            + ", ".join(sorted(unknown_statuses))
            + "."
        )
    _ensure_list_of_strings(payload.get("authority_classes"), "Поле authority_classes в memory trust policy")
    unknown_authorities = set(payload["authority_classes"]) - MEMORY_AUTHORITY_CLASS_VALUES
    if unknown_authorities:
        raise ValidationError(
            "Memory trust policy содержит неизвестные authority_classes: "
            + ", ".join(sorted(unknown_authorities))
            + "."
        )
    defaults = payload.get("defaults_by_source_kind")
    if not isinstance(defaults, dict) or not defaults:
        raise ValidationError("Поле defaults_by_source_kind в memory trust policy должно быть непустым JSON-объектом.")
    for source_kind, rule in defaults.items():
        if source_kind not in MEMORY_SOURCE_KIND_VALUES and source_kind not in {"ai_chat", "email_imap", "test", "*"}:
            raise ValidationError(f"Memory trust policy содержит неизвестный source_kind '{source_kind}'.")
        if not isinstance(rule, dict):
            raise ValidationError(f"Trust default для source_kind '{source_kind}' должен быть JSON-объектом.")
        _validate_trust_rule(rule, context=f"defaults_by_source_kind.{source_kind}")
    direct_context_policy = payload.get("direct_context_policy")
    if not isinstance(direct_context_policy, dict):
        raise ValidationError("Поле direct_context_policy в memory trust policy должно быть JSON-объектом.")
    allowed_statuses = direct_context_policy.get("allowed_trust_statuses")
    _ensure_list_of_strings(allowed_statuses, "Поле direct_context_policy.allowed_trust_statuses")
    if set(allowed_statuses) - MEMORY_TRUST_STATUS_VALUES:
        raise ValidationError("direct_context_policy.allowed_trust_statuses содержит неизвестные статусы.")
    allowed_authorities = direct_context_policy.get("allowed_authority_classes")
    _ensure_list_of_strings(allowed_authorities, "Поле direct_context_policy.allowed_authority_classes")
    if set(allowed_authorities) - MEMORY_AUTHORITY_CLASS_VALUES:
        raise ValidationError("direct_context_policy.allowed_authority_classes содержит неизвестные authority classes.")
    if not isinstance(direct_context_policy.get("require_trusted_for_context", True), bool):
        raise ValidationError("direct_context_policy.require_trusted_for_context должно быть boolean.")
    review_roles = payload.get("review_roles")
    if not isinstance(review_roles, dict):
        raise ValidationError("Поле review_roles в memory trust policy должно быть JSON-объектом.")


def validate_memory_claims_policy_payload(payload):
    _ensure_non_empty_mapping(payload, "Memory claims policy")
    missing = REQUIRED_MEMORY_CLAIMS_POLICY_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Memory claims policy не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for key in ("version", "name", "description"):
        if not isinstance(payload.get(key), str) or not payload.get(key):
            raise ValidationError(f"Поле '{key}' в memory claims policy должно быть непустой строкой.")
    _ensure_list_of_strings(payload.get("claim_types"), "Поле claim_types в memory claims policy")
    if set(payload["claim_types"]) - MEMORY_CLAIM_TYPE_VALUES:
        raise ValidationError("Memory claims policy содержит неизвестные claim_types.")
    _ensure_list_of_strings(payload.get("claim_statuses"), "Поле claim_statuses в memory claims policy")
    if set(payload["claim_statuses"]) - MEMORY_CLAIM_STATUS_VALUES:
        raise ValidationError("Memory claims policy содержит неизвестные claim_statuses.")
    _ensure_list_of_strings(payload.get("belief_statuses"), "Поле belief_statuses в memory claims policy")
    if set(payload["belief_statuses"]) - MEMORY_CLAIM_STATUS_VALUES:
        raise ValidationError("Memory claims policy содержит неизвестные belief_statuses.")
    for key in ("review_rules", "freshness_windows", "contradiction_policy"):
        if not isinstance(payload.get(key), dict):
            raise ValidationError(f"Поле {key} в memory claims policy должно быть JSON-объектом.")


def validate_memory_retrieval_budget_payload(payload):
    _ensure_non_empty_mapping(payload, "Memory retrieval budget")
    missing = REQUIRED_MEMORY_RETRIEVAL_BUDGET_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Memory retrieval budget не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for key in ("version", "name", "description"):
        if not isinstance(payload.get(key), str) or not payload.get(key):
            raise ValidationError(f"Поле '{key}' в memory retrieval budget должно быть непустой строкой.")
    hot_path = payload.get("hot_path")
    if not isinstance(hot_path, dict):
        raise ValidationError("Поле hot_path в memory retrieval budget должно быть JSON-объектом.")
    for key in ("raw_candidate_limit", "final_item_limit", "timeout_ms"):
        _ensure_positive_int(hot_path.get(key), f"hot_path.{key}")
    rank_fusion = payload.get("rank_fusion")
    if not isinstance(rank_fusion, dict):
        raise ValidationError("Поле rank_fusion в memory retrieval budget должно быть JSON-объектом.")
    for key in ("authority_boost", "freshness_boost", "scope_match_boost"):
        _ensure_number(rank_fusion.get(key), f"rank_fusion.{key}")
    boost_key = "reviewed_knowledge_boost" if "reviewed_knowledge_boost" in rank_fusion else "accepted_belief_boost"
    _ensure_number(rank_fusion.get(boost_key), f"rank_fusion.{boost_key}")
    for key in ("candidate_penalty", "contested_penalty", "expired_penalty", "low_confidence_penalty", "same_source_penalty"):
        _ensure_number(rank_fusion.get(key), f"rank_fusion.{key}")
    context_packing = payload.get("context_packing")
    if not isinstance(context_packing, dict):
        raise ValidationError("Поле context_packing в memory retrieval budget должно быть JSON-объектом.")
    for key in ("max_items", "max_tokens", "max_items_per_source"):
        _ensure_positive_int(context_packing.get(key), f"context_packing.{key}")
    llm_rerank = payload.get("optional_llm_rerank")
    if not isinstance(llm_rerank, dict) or not isinstance(llm_rerank.get("enabled", False), bool):
        raise ValidationError("optional_llm_rerank.enabled должно быть boolean.")
    if llm_rerank.get("enabled"):
        _ensure_positive_int(llm_rerank.get("top_k"), "optional_llm_rerank.top_k")
        _ensure_positive_int(llm_rerank.get("timeout_ms"), "optional_llm_rerank.timeout_ms")
    background = payload.get("background_batches")
    if not isinstance(background, dict):
        raise ValidationError("Поле background_batches в memory retrieval budget должно быть JSON-объектом.")
    for key in ("claim_extraction_batch_size", "digest_batch_size"):
        _ensure_positive_int(background.get(key), f"background_batches.{key}")


def _validate_memory_source_trust_fields(item, *, source_code: str) -> None:
    unknown_keys = set(item.keys()) & OPTIONAL_MEMORY_SOURCE_TRUST_KEYS
    if not unknown_keys:
        return
    rule = {
        key: item[key]
        for key in OPTIONAL_MEMORY_SOURCE_TRUST_KEYS
        if key in item
    }
    _validate_trust_rule(rule, context=f"memory source '{source_code}'")
    trusted_context_kinds = item.get("trusted_context_kinds")
    if trusted_context_kinds is not None:
        _ensure_list_of_strings(trusted_context_kinds, f"Поле trusted_context_kinds у memory source '{source_code}'")
        unknown_kinds = set(trusted_context_kinds) - MEMORY_CONTEXT_KIND_VALUES
        if unknown_kinds:
            raise ValidationError(
                f"Memory source '{source_code}' содержит неизвестные trusted_context_kinds: "
                + ", ".join(sorted(unknown_kinds))
                + "."
            )


def _validate_memory_source_policy_fields(item, *, source_code: str) -> None:
    unknown_keys = set(item.keys()) & OPTIONAL_MEMORY_SOURCE_POLICY_KEYS
    if not unknown_keys:
        return
    source_origin = item.get("source_origin")
    if source_origin is not None and source_origin not in MEMORY_SOURCE_ORIGIN_VALUES:
        raise ValidationError(f"Memory source '{source_code}' содержит недопустимый source_origin.")
    privacy_profile = item.get("privacy_profile")
    if privacy_profile is not None and privacy_profile not in MEMORY_PRIVACY_PROFILE_VALUES:
        raise ValidationError(f"Memory source '{source_code}' содержит недопустимый privacy_profile.")
    access_policy = item.get("access_policy")
    if access_policy is not None:
        if not isinstance(access_policy, dict):
            raise ValidationError(f"Поле access_policy у memory source '{source_code}' должно быть JSON-объектом.")
        mode = access_policy.get("mode")
        if mode not in MEMORY_ACCESS_POLICY_MODE_VALUES:
            raise ValidationError(f"Memory source '{source_code}' содержит недопустимый access_policy.mode.")
        scope_tokens = access_policy.get("scope_tokens", [])
        if scope_tokens is not None and (
            not isinstance(scope_tokens, list) or not all(isinstance(token, str) and token for token in scope_tokens)
        ):
            raise ValidationError(f"Поле access_policy.scope_tokens у memory source '{source_code}' должно быть списком строк.")
        policy_ref = access_policy.get("policy_ref", "")
        if policy_ref is not None and not isinstance(policy_ref, str):
            raise ValidationError(f"Поле access_policy.policy_ref у memory source '{source_code}' должно быть строкой.")


def _validate_trust_rule(rule, *, context: str) -> None:
    trust_status = rule.get("trust_status")
    if trust_status is not None and trust_status not in MEMORY_TRUST_STATUS_VALUES:
        raise ValidationError(f"{context} содержит недопустимый trust_status.")
    authority_class = rule.get("authority_class")
    if authority_class is not None and authority_class not in MEMORY_AUTHORITY_CLASS_VALUES:
        raise ValidationError(f"{context} содержит недопустимый authority_class.")
    if "trusted_for_context" in rule and not isinstance(rule.get("trusted_for_context"), bool):
        raise ValidationError(f"{context}: trusted_for_context должно быть boolean.")
    if "requires_source_review" in rule and not isinstance(rule.get("requires_source_review"), bool):
        raise ValidationError(f"{context}: requires_source_review должно быть boolean.")
    review_owner = rule.get("review_owner")
    if review_owner is not None and (not isinstance(review_owner, str) or not review_owner):
        raise ValidationError(f"{context}: review_owner должен быть непустой строкой.")
    untrusted_handling = rule.get("untrusted_handling")
    if untrusted_handling is not None and untrusted_handling not in MEMORY_UNTRUSTED_HANDLING_VALUES:
        raise ValidationError(f"{context} содержит недопустимый untrusted_handling.")


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


def validate_memory_file_organization_profiles_payload(payload):
    _ensure_non_empty_mapping(payload, "Memory file organization profiles")
    missing = REQUIRED_MEMORY_FILE_ORGANIZATION_ROOT_KEYS - set(payload.keys())
    if missing:
        raise ValidationError(
            f"Memory file organization profiles не содержит обязательные поля: {', '.join(sorted(missing))}."
        )
    for key in ("version", "name", "description"):
        if not isinstance(payload.get(key), str) or not payload.get(key):
            raise ValidationError(f"Поле '{key}' в memory file organization profiles должно быть непустой строкой.")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValidationError("Поле profiles в memory file organization profiles должно быть непустым JSON-объектом.")

    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            raise ValidationError(f"File organization profile '{profile_id}' должен быть JSON-объектом.")
        missing_profile_keys = REQUIRED_MEMORY_FILE_ORGANIZATION_PROFILE_KEYS - set(profile.keys())
        if missing_profile_keys:
            raise ValidationError(
                f"File organization profile '{profile_id}' не содержит обязательные поля: "
                f"{', '.join(sorted(missing_profile_keys))}."
            )
        if type(profile.get("enabled")) is not bool:
            raise ValidationError(f"Поле enabled у file organization profile '{profile_id}' должно быть boolean.")
        for key in ("source_code", "incoming_path", "baseline_profile", "physical_move_policy", "storage_backend"):
            if not isinstance(profile.get(key), str) or not profile.get(key):
                raise ValidationError(f"Поле {key} у file organization profile '{profile_id}' должно быть непустой строкой.")
        managed_root = profile.get("managed_root")
        if not isinstance(managed_root, str):
            raise ValidationError(f"Поле managed_root у file organization profile '{profile_id}' должно быть строкой.")
        if _path_looks_absolute_or_unc(profile.get("incoming_path", "")):
            raise ValidationError(f"Поле incoming_path у file organization profile '{profile_id}' должно быть относительным путем.")
        if profile["physical_move_policy"] not in MEMORY_FILE_ORGANIZATION_PHYSICAL_MOVE_POLICY_VALUES:
            raise ValidationError(f"File organization profile '{profile_id}' содержит недопустимый physical_move_policy.")
        if profile["storage_backend"] not in MEMORY_FILE_ORGANIZATION_STORAGE_BACKEND_VALUES:
            raise ValidationError(f"File organization profile '{profile_id}' содержит недопустимый storage_backend.")
        future_backends = profile.get("future_backends")
        _ensure_list_of_strings(future_backends, f"Поле future_backends у file organization profile '{profile_id}'")
        unknown_backends = set(future_backends) - MEMORY_FILE_ORGANIZATION_STORAGE_BACKEND_VALUES
        if unknown_backends:
            raise ValidationError(
                f"File organization profile '{profile_id}' содержит неизвестные future_backends: "
                + ", ".join(sorted(unknown_backends))
                + "."
            )
        delete_policy = profile.get("source_delete_policy")
        if not isinstance(delete_policy, dict):
            raise ValidationError(f"Поле source_delete_policy у file organization profile '{profile_id}' должно быть JSON-объектом.")
        missing_delete_keys = REQUIRED_MEMORY_FILE_SOURCE_DELETE_POLICY_KEYS - set(delete_policy.keys())
        if missing_delete_keys:
            raise ValidationError(
                f"source_delete_policy у file organization profile '{profile_id}' не содержит поля: "
                f"{', '.join(sorted(missing_delete_keys))}."
            )
        if delete_policy.get("mode") not in MEMORY_FILE_ORGANIZATION_DELETE_MODE_VALUES:
            raise ValidationError(f"File organization profile '{profile_id}' содержит недопустимый source_delete_policy.mode.")
        if type(delete_policy.get("retention_days")) is not int or delete_policy["retention_days"] < 0:
            raise ValidationError(f"source_delete_policy.retention_days у file organization profile '{profile_id}' должно быть числом >= 0.")
        if type(delete_policy.get("requires_backup_checkpoint")) is not bool:
            raise ValidationError(
                f"source_delete_policy.requires_backup_checkpoint у file organization profile '{profile_id}' должно быть boolean."
            )
        thresholds = profile.get("proposal_thresholds")
        if not isinstance(thresholds, dict):
            raise ValidationError(f"Поле proposal_thresholds у file organization profile '{profile_id}' должно быть JSON-объектом.")
        for key in ("min_users", "min_events", "min_files", "min_confidence"):
            if key not in thresholds:
                raise ValidationError(f"proposal_thresholds у file organization profile '{profile_id}' не содержит {key}.")
        for key in ("min_users", "min_events", "min_files"):
            if type(thresholds.get(key)) is not int or thresholds[key] < 1:
                raise ValidationError(f"proposal_thresholds.{key} у file organization profile '{profile_id}' должно быть положительным числом.")
        min_confidence = thresholds.get("min_confidence")
        if not isinstance(min_confidence, (int, float)) or min_confidence < 0 or min_confidence > 1:
            raise ValidationError(f"proposal_thresholds.min_confidence у file organization profile '{profile_id}' должен быть между 0 и 1.")


def _path_looks_absolute_or_unc(path_value: str) -> bool:
    value = str(path_value or "").strip()
    return value.startswith("/") or value.startswith("\\\\") or re.match(r"^[A-Za-z]:[\\/]", value) is not None


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
