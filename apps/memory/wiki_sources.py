"""Read trusted, current source projections for a wiki audience without opening an origin path."""

import re

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.source_adapters import ACCESS_MODE_ADAPTER_CHECK, get_source_adapter

from .config_documents import (
    get_memory_document_payload,
    get_memory_document_snapshots,
    get_memory_test_source_allowlist,
)
from .deidentification import detect_pii
from .models import MemorySearchDocument, MemorySource, MemorySourceObject
from .policies import (
    PUBLIC_SCOPE_TOKEN,
    source_allows_direct_context,
    source_object_scope_tokens,
    user_scope_tokens,
)
from .routing import resolve_retrieval_route
from .security import scan_for_secrets
from .services import can_access_source_object, sha256_text
from .wiki_config import WikiBundle

_DENIED = "Источник недоступен для этой вики."
_SENSITIVITY = {"public": 0, "internal": 1, "confidential": 2}
_REF_FIELDS = {"source_code", "source_object_id", "text_hash"}
_WORKORDER_FIELD = re.compile(
    r"^(?=(?:Описание|Подразделение|Доска|Статус|Приоритет|Оборудование|Исполнитель|"
    r"Оценка|Комментарий|Переход статуса):)", re.MULTILINE,
)


def _safe_for_model(text, *, workorder_fields=False):
    # The typed adapter renders one "field: value" per line. Mark genuine
    # field labels as boundaries: "Новая\nПриоритет:" otherwise looks like a
    # full name. PII across free-text lines and the original credentials scan
    # still see the entire text. Only the detector receives these separators.
    pii_text = _WORKORDER_FIELD.sub("|", text) if workorder_fields else text
    return not scan_for_secrets(text).blocked and not any(
        finding.entity_type != "DATE" for finding in detect_pii(pii_text)
    )


def _audience_allowed(actor, bundle, obj, snapshot_metadata, snapshots):
    audience = set(bundle.read_tokens)
    if not audience.intersection(user_scope_tokens(actor)) or not can_access_source_object(actor, obj, snapshots=snapshots):
        return False
    allowed = set(source_object_scope_tokens(obj, snapshots=snapshots))
    metadata = obj.metadata or {}
    policy = metadata.get("access_policy") or {}
    if not isinstance(policy, dict):
        return False
    dynamic = policy.get("mode") == ACCESS_MODE_ADAPTER_CHECK
    adapter = get_source_adapter(obj.source.code)
    if dynamic or metadata.get("source_adapter") or adapter:
        if adapter is None:
            return False
        try:
            record = adapter.get_object(obj.object_id)
            if record is None:
                return False
            current = adapter.render_envelope(record)
            if (current.operation != "upsert" or current.source_code != obj.source.code
                    or current.object_id != obj.object_id or current.content_hash != obj.content_hash
                    or dict(current.access_policy) != policy
                    or current.sensitivity != snapshot_metadata["sensitivity"]
                    or current.privacy_profile != metadata.get("privacy_profile")):
                return False
        except Exception:
            # Adapter diagnostics can contain source data.
            return False
    for token in audience:
        if not dynamic and (token in allowed or PUBLIC_SCOPE_TOKEN in allowed):
            continue
        # A changing object predicate cannot authorize an entire group. For
        # named users, check both their scope and the live adapter permission.
        match = re.fullmatch(r"user:([1-9][0-9]{0,17})", token)
        if not match:
            return False
        reader = get_user_model().objects.filter(pk=int(match[1]), is_active=True).first()
        if not user_scope_tokens(reader).intersection(allowed):
            return False
        if dynamic and not can_access_source_object(reader, obj, snapshots=snapshots):
            return False
    return True


def _registered_source(code, snapshots):
    sources = get_memory_document_payload("memory.contract.sources", snapshots=snapshots) or []
    return any(
        isinstance(row, dict) and row.get("code") == code and row.get("enabled", True)
        for row in sources
    ) or code in get_memory_test_source_allowlist()


def wiki_source_preview(actor, bundle: WikiBundle, source_code: str, source_object_id: str) -> dict:
    """Return a versioned, safe source excerpt from the current LBS projection.

    The model destination of these tools may be remote. Only cloud-approved
    levels and the existing source-of-truth checks can release text.
    """
    if not (isinstance(source_code, str) and 0 < len(source_code) <= 120
            and isinstance(source_object_id, str) and 0 < len(source_object_id) <= 255
            and bundle.model_context and bundle.sensitivity in _SENSITIVITY):
        raise PermissionDenied(_DENIED)
    snapshots = get_memory_document_snapshots(document_ids=(
        "memory.contract.sources", "memory.contract.routing",
        "memory.contract.trust_policy", "memory.contract.ingestion_profiles",
    ))
    if not _registered_source(source_code, snapshots):
        raise PermissionDenied(_DENIED)
    projections = MemorySearchDocument.objects.select_related("source_object__source").filter(
        corpus_type=MemorySearchDocument.CorpusType.SOURCE_DATA,
        object_kind=MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
        index_status=MemorySearchDocument.IndexStatus.READY,
        source_object__source__code=source_code,
        source_object__source__status=MemorySource.Status.ENABLED,
        source_object__object_id=source_object_id,
        source_object__discovery_status=MemorySourceObject.DiscoveryStatus.SEEN,
        source_object__ingestion_status=MemorySourceObject.IngestionStatus.INGESTED,
    )
    doc = projections.first()
    if doc is None:
        raise PermissionDenied(_DENIED)
    obj = doc.source_object
    source = obj.source
    metadata = doc.metadata or {}
    if not source_allows_direct_context(source, "retrieved_chunk", snapshots=snapshots):
        raise PermissionDenied(_DENIED)
    levels = {source.sensitivity, metadata.get("sensitivity"), bundle.sensitivity}
    if any(_SENSITIVITY.get(level, 99) > _SENSITIVITY[bundle.sensitivity] for level in levels):
        raise PermissionDenied(_DENIED)
    route = resolve_retrieval_route(sorted(levels), snapshots=snapshots)
    if not all(route.routes[level].get("cloud_allowed") for level in levels):
        raise PermissionDenied(_DENIED)
    if not _audience_allowed(actor, bundle, obj, metadata, snapshots):
        raise PermissionDenied(_DENIED)
    # The ordinary renderer can return a live, unredacted adapter envelope or a
    # fallback filename. Use only the actual text accepted by the privacy gate.
    text = (obj.metadata or {}).get("safe_text")
    if not isinstance(text, str) or not text.strip() or not obj.content_hash or metadata.get("content_hash") != obj.content_hash:
        raise PermissionDenied(_DENIED)
    digest = sha256_text(text)
    if digest != doc.body_hash or digest != metadata.get("safe_text_hash"):
        raise PermissionDenied(_DENIED)
    workorder_fields = source_code == "workorders" and (obj.metadata or {}).get("source_adapter") == "workorders"
    if not _safe_for_model(text, workorder_fields=workorder_fields) or not _safe_for_model(f"{source_code}\n{source_object_id}"):
        raise PermissionDenied(_DENIED)
    # Re-read the projection after dynamic checks. Changes during live adapter
    # reads or privacy scanning must not release a superseded text or policy.
    if not projections.filter(
        pk=doc.pk, body_hash=digest, updated_at=doc.updated_at,
        source_object__updated_at=obj.updated_at, source_object__content_hash=obj.content_hash,
        source_object__source__updated_at=source.updated_at,
    ).exists():
        raise PermissionDenied(_DENIED)
    return {
        "source_ref": {"source_code": source_code, "source_object_id": source_object_id, "text_hash": digest},
        "text": text,
    }


def wiki_sources_allowed(actor, bundle: WikiBundle, refs) -> bool:
    """Recheck the exact text version, source status and audience for each citation."""
    if not isinstance(refs, list):
        return False
    for ref in refs:
        if (not isinstance(ref, dict) or set(ref) != _REF_FIELDS
                or not isinstance(ref["text_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["text_hash"])):
            return False
        try:
            preview = wiki_source_preview(actor, bundle, ref["source_code"], ref["source_object_id"])
        except (PermissionDenied, ValidationError):
            return False
        if preview["source_ref"] != ref:
            return False
    return True
