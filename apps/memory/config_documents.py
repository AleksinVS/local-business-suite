from apps.memory.contracts import (
    validate_memory_claims_policy_payload,
    validate_memory_file_organization_profiles_payload,
    validate_memory_graph_schema_payload,
    validate_memory_ingestion_profiles_payload,
    validate_memory_profiles_payload,
    validate_memory_retrieval_budget_payload,
    validate_memory_routing_payload,
    validate_memory_sources_payload,
    validate_memory_trust_policy_payload,
)
from apps.settings_center.document_specs import ConfigDocumentSpec


def cross_validate_memory_sources(candidate, related_payloads):
    validate_memory_sources_payload(
        candidate,
        profiles_payload=related_payloads["memory.contract.profiles"],
        routing_payload=related_payloads["memory.contract.routing"],
        ingestion_profiles_payload=related_payloads["memory.contract.ingestion_profiles"],
    )


def _spec(
    name,
    validator,
    *,
    storage_policy="database_override",
    write_policy=None,
    consumer_classes=(),
    cross_document_ids=(),
    cross_validator=None,
    requires_reindex=False,
    sensitivity="internal",
):
    return ConfigDocumentSpec(
        document_id=f"memory.contract.{name.removeprefix('memory_')}",
        domain="memory",
        storage_policy=storage_policy,
        default_path=f"contracts/ai/{name}.json",
        schema_version=1,
        validator=validator,
        failure_policy="fail_closed",
        write_policy=write_policy
        or ("editable" if storage_policy == "database_override" else "read_only"),
        required_permission="manage_settings",
        owner="memory",
        legacy_settings_path=(
            f"LOCAL_BUSINESS_MEMORY_{name.removeprefix('memory_').upper()}_FILE"
        ),
        cross_document_ids=cross_document_ids,
        cross_validator=cross_validator,
        requires_reindex=requires_reindex,
        delivery_scope="job",
        consumer_classes=consumer_classes,
        sensitivity=sensitivity,
        active_backend="git" if storage_policy == "git_static" else "legacy_file",
    )


def get_document_specs():
    return [
        _spec(
            "memory_sources",
            validate_memory_sources_payload,
            consumer_classes=("memory",),
            cross_document_ids=(
                "memory.contract.profiles",
                "memory.contract.routing",
                "memory.contract.ingestion_profiles",
            ),
            cross_validator=cross_validate_memory_sources,
            requires_reindex=True,
            sensitivity="restricted",
        ),
        _spec(
            "memory_profiles",
            validate_memory_profiles_payload,
            consumer_classes=("memory",),
            requires_reindex=True,
        ),
        _spec(
            "memory_routing",
            validate_memory_routing_payload,
            consumer_classes=("memory",),
            sensitivity="restricted",
        ),
        _spec(
            "memory_trust_policy",
            validate_memory_trust_policy_payload,
            consumer_classes=("memory",),
            requires_reindex=True,
            sensitivity="restricted",
        ),
        _spec(
            "memory_claims_policy",
            validate_memory_claims_policy_payload,
            storage_policy="git_static",
            consumer_classes=("memory",),
            sensitivity="restricted",
        ),
        _spec(
            "memory_retrieval_budget",
            validate_memory_retrieval_budget_payload,
            consumer_classes=("memory",),
        ),
        _spec(
            "memory_ingestion_profiles",
            validate_memory_ingestion_profiles_payload,
            consumer_classes=("memory",),
            requires_reindex=True,
            sensitivity="restricted",
        ),
        _spec(
            "memory_file_organization_profiles",
            validate_memory_file_organization_profiles_payload,
            consumer_classes=("filehub",),
            sensitivity="restricted",
        ),
        _spec(
            "memory_graph_schema",
            validate_memory_graph_schema_payload,
            write_policy="requires_domain_workflow",
            consumer_classes=("memory",),
            requires_reindex=True,
            sensitivity="restricted",
        ),
    ]
