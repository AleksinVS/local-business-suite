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


# These are value documents, not process settings.  Callers must obtain their
# values at the beginning of an operation and pass the resulting snapshot down
# to item-level helpers.  Keeping the list here also gives architecture checks
# one stable source for the memory document boundary.
MEMORY_DOCUMENT_IDS = (
    "memory.contract.sources",
    "memory.contract.profiles",
    "memory.contract.routing",
    "memory.contract.trust_policy",
    "memory.contract.claims_policy",
    "memory.contract.retrieval_budget",
    "memory.contract.ingestion_profiles",
    "memory.contract.file_organization_profiles",
    "memory.contract.graph_schema",
)


def get_memory_document_snapshots(*, document_ids=None, request=None):
    """Read one immutable operation snapshot for memory configuration.

    ``ConfigDocumentRepository`` performs one read for the connected document
    scope and returns defensive copies.  This adapter deliberately exposes
    payloads only after that single read, so loops over files/items cannot
    accidentally consult the repository again.
    """

    ids = tuple(document_ids or MEMORY_DOCUMENT_IDS)
    # Lazy import avoids the registry -> domain specs -> repository import
    # cycle during Django startup.
    from apps.settings_center.document_repository import get_snapshot

    snapshots = get_snapshot(ids, request=request)
    return {document_id: snapshots[document_id] for document_id in ids}


def get_memory_document_payload(document_id, *, snapshots=None, request=None):
    """Return a payload from an already captured operation snapshot.

    Passing ``snapshots`` is required by long-running operations.  The
    optional repository read keeps small standalone callers compatible while
    still avoiding any process-start payload constants.
    """

    # Django's ``override_settings`` is intentionally supported for the
    # existing unit/integration fixtures.  It is a test-only holder, never the
    # production settings object; production always uses the repository above.
    test_payload = _test_override_payload(document_id)
    if test_payload is not None:
        return test_payload
    if snapshots is None:
        snapshots = get_memory_document_snapshots(document_ids=(document_id,), request=request)
    snapshot = snapshots[document_id]
    return snapshot.payload if hasattr(snapshot, "payload") else snapshot


def _test_override_payload(document_id):
    """Return an explicit Django test override, if one is active."""

    from django.conf import settings

    wrapped = getattr(settings, "_wrapped", None)
    if wrapped is None or wrapped.__class__.__name__ != "UserSettingsHolder":
        return None
    attribute_by_document = {
        "memory.contract.sources": "LOCAL_BUSINESS_MEMORY_SOURCES",
        "memory.contract.profiles": "LOCAL_BUSINESS_MEMORY_PROFILES",
        "memory.contract.routing": "LOCAL_BUSINESS_MEMORY_ROUTING",
        "memory.contract.trust_policy": "LOCAL_BUSINESS_MEMORY_TRUST_POLICY",
        "memory.contract.claims_policy": "LOCAL_BUSINESS_MEMORY_CLAIMS_POLICY",
        "memory.contract.retrieval_budget": "LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET",
        "memory.contract.ingestion_profiles": "LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES",
        "memory.contract.file_organization_profiles": "LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES",
        "memory.contract.graph_schema": "LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA",
    }
    attribute = attribute_by_document.get(document_id)
    # ``UserSettingsHolder`` delegates ``hasattr``/``is_overridden`` to its
    # defaults, so those checks also match ordinary settings such as DATA_DIR.
    # Only an attribute placed directly on the holder is an explicit fixture
    # override and may bypass the repository.
    if attribute is None or attribute not in getattr(wrapped, "__dict__", {}):
        return None
    return getattr(wrapped, attribute)


def get_memory_test_override_payload(document_id):
    """Return an explicitly overridden payload for compatibility fixtures.

    This hook is intentionally separate from the production reader.  Runtime
    code must pass repository snapshots; only tests that explicitly override a
    migrated payload may use this path.
    """

    return _test_override_payload(document_id)


def get_memory_test_source_allowlist() -> frozenset[str]:
    """Return explicitly registered fixture sources, never a production default."""

    from django.conf import UserSettingsHolder, settings

    wrapped = getattr(settings, "_wrapped", None)
    if not isinstance(wrapped, UserSettingsHolder):
        return frozenset()
    # The marker must be placed on a disposable Django test holder. Nested
    # ``self.settings(...)`` contexts may wrap that holder, so walk only the
    # explicit UserSettingsHolder chain; production ``Settings`` and arbitrary
    # wrappers are never accepted.
    current = wrapped
    while isinstance(current, UserSettingsHolder):
        values = current.__dict__.get("LOCAL_BUSINESS_MEMORY_TEST_SOURCE_ALLOWLIST", ())
        if values:
            return frozenset(
                str(value).strip() for value in values if str(value).strip()
            )
        current = getattr(current, "default_settings", None)
    return frozenset()


def cross_validate_memory_sources(candidate, related_payloads):
    validate_memory_sources_payload(
        candidate,
        profiles_payload=related_payloads["memory.contract.profiles"],
        routing_payload=related_payloads["memory.contract.routing"],
        ingestion_profiles_payload=related_payloads["memory.contract.ingestion_profiles"],
    )


def enqueue_memory_reindex_outbox(
    document_id: str,
    revision: int,
    content_hash: str,
    change_id: int,
):
    """Domain callback stored on memory specs, invoked by the generic writer."""

    from .services import enqueue_memory_reindex_for_document_revision

    return enqueue_memory_reindex_for_document_revision(
        document_id=document_id,
        revision=revision,
        content_hash=content_hash,
        change_id=change_id,
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
            if storage_policy != "git_static"
            else None
        ),
        cross_document_ids=cross_document_ids,
        cross_validator=cross_validator,
        requires_reindex=requires_reindex,
        transactional_outbox_callback=(
            enqueue_memory_reindex_outbox if requires_reindex else None
        ),
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
