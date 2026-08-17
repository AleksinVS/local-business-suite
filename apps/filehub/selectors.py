"""Scoped read and authorization helpers for the file organization contour.

File organization is a source-wide operation only when the actor has an
explicit source scope.  Seeing one source object through an adapter is not a
substitute for source-wide authorization.
"""

from __future__ import annotations

import hashlib
import json

from apps.memory.models import MemorySearchDocument, MemorySource, MemorySourceObject
from apps.memory.policies import (
    can_access_search_document,
    resolve_active_actor,
    scope_tokens_match,
    source_scope_tokens,
    user_scope_tokens,
)
from apps.memory.services import can_access_source_object_via_adapter

from .models import MemoryFileObject


def can_access_source_for_organization(actor, source: MemorySource | None) -> bool:
    """Return whether *actor* may see or mutate source-wide file metadata."""

    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None or source is None or not getattr(source, "pk", None):
        return False
    source = MemorySource.objects.filter(pk=source.pk).first()
    if source is None:
        return False
    if source.status != MemorySource.Status.ENABLED:
        return False
    if getattr(actor, "is_superuser", False):
        return True
    required = source_scope_tokens(source)
    if not required or not scope_tokens_match(required, user_scope_tokens(actor)):
        return False
    # An adapter can answer object-level questions only.  It cannot establish
    # that the actor may enumerate the complete source.
    mode = ((source.config or {}).get("access_policy") or {}).get("mode")
    if mode in {"adapter_check", "adapter"}:
        return False
    # Source-wide metadata is safe only when every relevant file has a
    # currently bound and accessible source object.  A single unknown or
    # revoked file makes the source incomplete for this operation.
    files = MemoryFileObject.objects.filter(source=source).select_related(
        "source", "current_version", "current_version__source_object", "current_physical_placement"
    )
    if not files.exists():
        return False
    if MemorySourceObject.objects.filter(source=source, file_versions__isnull=True).exists():
        return False
    return all(can_access_file_object(actor, file_object) for file_object in files)


def source_scope_is_complete(actor, source: MemorySource | None) -> bool:
    return can_access_source_for_organization(actor, source)


def can_access_file_object(actor, file_object: MemoryFileObject | None) -> bool:
    """Apply token scope and the current source adapter check to one file."""

    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None or file_object is None:
        return False
    # Source status is an invariant, not an authorization shortcut.  Check it
    # before the superuser branch as well: disabled sources are never exposed
    # through the file organization contour.
    source = MemorySource.objects.filter(pk=getattr(file_object, "source_id", None)).first()
    if source is None or source.status != MemorySource.Status.ENABLED:
        return False
    if getattr(actor, "is_superuser", False):
        return True
    source_object = _source_object_for_file(file_object)
    if source_object is None:
        return False
    if getattr(file_object, "source_id", None) != getattr(source_object, "source_id", None):
        return False
    if not can_access_source_object_via_adapter(actor, source_object):
        return False
    required = list((source_object.metadata or {}).get("scope_tokens") or [])
    if not required:
        required = list(((source_object.metadata or {}).get("acl") or {}).get("scope_tokens") or [])
    if not required:
        document = MemorySearchDocument.objects.filter(source_object=source_object).first()
        if document is not None:
            return can_access_search_document(actor, document)
    return scope_tokens_match(required, user_scope_tokens(actor))


def visible_file_objects(actor, *, source=None):
    queryset = MemoryFileObject.objects.select_related(
        "source",
        "current_physical_placement",
        "current_version",
        "current_version__source_object",
    ).filter(source__status=MemorySource.Status.ENABLED)
    if source is not None:
        source = MemorySource.objects.filter(pk=getattr(source, "pk", None)).first()
        if source is None:
            return queryset.none()
        queryset = queryset.filter(source=source)
    actor = resolve_active_actor(actor, force_refresh=True)
    if actor is None:
        return queryset.none()
    if source is not None and source.status != MemorySource.Status.ENABLED:
        return queryset.none()
    if getattr(actor, "is_superuser", False):
        return queryset.filter(source__status=MemorySource.Status.ENABLED)
    return [file_object for file_object in queryset if can_access_file_object(actor, file_object)]


def proposal_membership_is_visible(actor, proposal) -> bool:
    """Dashboard proposals must carry one valid, current scoped membership."""

    if not can_access_source_for_organization(actor, proposal.source):
        return False
    raw_ids = (proposal.metadata or {}).get("file_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return False
    file_ids = sorted({str(value).strip() for value in raw_ids if str(value).strip()})
    if len(file_ids) != len(raw_ids) or len(file_ids) != proposal.affected_file_count:
        return False
    payload = {
        "source": proposal.source.code,
        "bucket": (proposal.proposed_rule or {}).get("bucket") or "",
        "file_ids": file_ids,
    }
    fingerprint = "sha256:" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if (proposal.metadata or {}).get("membership_fingerprint") != fingerprint:
        return False
    files = MemoryFileObject.objects.filter(source=proposal.source, file_id__in=file_ids).select_related(
        "current_version", "current_physical_placement"
    )
    if files.count() != len(file_ids):
        return False
    return all(can_access_file_object(actor, file_object) for file_object in files)


def _source_object_for_file(file_object):
    version = getattr(file_object, "current_version", None)
    source_object = getattr(version, "source_object", None)
    if source_object is not None:
        return source_object
    placement = (
        file_object.physical_placements.select_related("source_object")
        .filter(
            source_object__isnull=False,
            source_object__source_id=file_object.source_id,
            storage_backend="source_fs",
            path_role="source_current",
            placement_status="active",
            is_current=True,
        )
        .order_by("-is_current", "-updated_at", "-id")
        .first()
    )
    return placement.source_object if placement is not None else None
