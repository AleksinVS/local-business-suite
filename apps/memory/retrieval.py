from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError

from .graph_backends import DjangoGraphMemoryBackend
from .models import MemoryChunk, MemoryGraphFact, MemorySnapshot
from .policies import can_access_chunk, can_access_graph_fact, user_scope_tokens
from .routing import resolve_retrieval_route, route_allows_context_kind
from .services import record_access_audit
from .vector_backends import get_default_backend


DEFAULT_LIMIT = 5
MAX_LIMIT = 50
PATH_METADATA_KEYS = {"raw_path", "safe_path", "text_path", "path"}


def memory_search(
    actor,
    query,
    scope_tokens=None,
    sensitivity=None,
    limit=DEFAULT_LIMIT,
    vector_backend=None,
    graph_backend=None,
    request_id="",
):
    query_text = _normalize_query(query)
    query_hash = _query_hash(query_text)
    normalized_limit = _normalize_limit(limit)
    trace: dict[str, Any] = {"filtered": {}}

    try:
        _assert_actor(actor)
        route_decision = resolve_retrieval_route(sensitivity)
        trace["route"] = route_decision.as_trace()

        effective_scope_tokens = _effective_scope_tokens(actor, scope_tokens)
        vector_candidates = _search_vector_candidates(
            vector_backend=vector_backend,
            query=query_text,
            scope_tokens=effective_scope_tokens,
            sensitivity=route_decision.allowed_sensitivities,
            limit=normalized_limit,
        )
        graph_candidates = _search_graph_candidates(
            graph_backend=graph_backend,
            actor=actor,
            query=query_text,
            scope_tokens=effective_scope_tokens,
            sensitivity=route_decision.allowed_sensitivities,
            limit=normalized_limit,
        )
        trace["candidate_counts"] = {
            "vector": len(vector_candidates),
            "graph": len(graph_candidates),
        }

        citations_by_id: dict[str, dict] = {}
        items = []
        returned_chunk_ids: list[str] = []
        returned_fact_ids: list[str] = []

        for item in _chunk_items(
            actor=actor,
            candidates=vector_candidates,
            allowed_sensitivities=route_decision.allowed_sensitivities,
            trace=trace,
        ):
            _append_item(item, items, citations_by_id, returned_chunk_ids, returned_fact_ids, normalized_limit)
            if len(items) >= normalized_limit:
                break

        if len(items) < normalized_limit:
            for item in _graph_items(
                actor=actor,
                candidates=graph_candidates,
                allowed_sensitivities=route_decision.allowed_sensitivities,
                trace=trace,
            ):
                _append_item(item, items, citations_by_id, returned_chunk_ids, returned_fact_ids, normalized_limit)
                if len(items) >= normalized_limit:
                    break

        citations = list(citations_by_id.values())
        result = {
            "items": items,
            "citations": citations,
            "meta": {
                "request_id": request_id,
                "query_hash": query_hash,
                "limit": normalized_limit,
                "returned_count": len(items),
                "citation_count": len(citations),
                "route": route_decision.as_trace(),
            },
        }
        trace["returned_count"] = len(items)
        trace["citation_count"] = len(citations)
        record_access_audit(
            actor=actor,
            request_id=request_id,
            query_hash=query_hash,
            returned_chunk_ids=returned_chunk_ids,
            returned_fact_ids=returned_fact_ids,
            policy_decision="allowed",
            retrieval_trace=trace,
        )
        return result
    except (PermissionDenied, ValidationError) as exc:
        _audit_denied(
            actor=actor,
            request_id=request_id,
            query_hash=query_hash,
            reason=str(exc),
            trace=trace,
        )
        raise


def read_safe_chunk_text(chunk: MemoryChunk) -> str:
    path = _resolve_safe_text_path(chunk.text_path)
    return path.read_text(encoding="utf-8")


def _search_vector_candidates(*, vector_backend, query, scope_tokens, sensitivity, limit):
    backend = vector_backend or get_default_backend()
    if backend is None:
        return []
    if not hasattr(backend, "search"):
        raise ValidationError("Vector memory backend must provide search().")
    return list(
        backend.search(
            query,
            scope_tokens=scope_tokens,
            sensitivity=sensitivity,
            limit=_candidate_limit(limit),
        )
    )


def _search_graph_candidates(*, graph_backend, actor, query, scope_tokens, sensitivity, limit):
    backend = graph_backend or DjangoGraphMemoryBackend()
    if backend is None:
        return []
    if not hasattr(backend, "search_facts"):
        raise ValidationError("Graph memory backend must provide search_facts().")
    return list(
        backend.search_facts(
            query,
            scope_tokens=scope_tokens,
            sensitivity=sensitivity,
            active_only=True,
            user=actor,
            limit=_candidate_limit(limit),
        )
    )


def _chunk_items(*, actor, candidates, allowed_sensitivities, trace):
    chunk_ids = [_candidate_id(candidate, "chunk_id") for candidate in candidates]
    chunks = _chunks_by_id(chunk_ids)

    for candidate in candidates:
        chunk_id = _candidate_id(candidate, "chunk_id")
        chunk = chunks.get(chunk_id)
        if chunk is None:
            _bump(trace, "missing_chunk")
            continue
        if not _chunk_route_allowed(chunk, allowed_sensitivities):
            _bump(trace, "route_denied_chunk")
            continue
        if not can_access_chunk(actor, chunk):
            _bump(trace, "policy_denied_chunk")
            continue
        if not _chunk_is_retrievable(chunk):
            _bump(trace, "inactive_or_blocked_chunk")
            continue

        citation = _chunk_citation(chunk)
        if citation is None:
            _bump(trace, "missing_chunk_citation")
            continue
        try:
            text = read_safe_chunk_text(chunk)
        except (OSError, ValidationError):
            _bump(trace, "unsafe_or_missing_chunk_text")
            continue

        yield {
            "id": chunk.chunk_id,
            "kind": "memory_chunk",
            "text": text,
            "score": _candidate_score(candidate),
            "citation_ids": [citation["id"]],
            "citations": [citation],
            "metadata": _safe_metadata(
                {
                    **_candidate_metadata(candidate),
                    **dict(chunk.metadata or {}),
                    "source_code": chunk.source_code,
                    "source_object_id": chunk.source_object_id,
                    "snapshot_hash": chunk.snapshot_hash,
                    "position": chunk.position,
                    "sensitivity": chunk.sensitivity,
                }
            ),
        }


def _graph_items(*, actor, candidates, allowed_sensitivities, trace):
    fact_ids = [_candidate_id(candidate, "fact_id") for candidate in candidates]
    facts = _facts_by_id(fact_ids)

    for candidate in candidates:
        fact_id = _candidate_id(candidate, "fact_id")
        fact = facts.get(fact_id)
        if fact is None and isinstance(candidate, MemoryGraphFact):
            fact = candidate
        if fact is None:
            _bump(trace, "missing_fact")
            continue
        if not _fact_route_allowed(fact, allowed_sensitivities):
            _bump(trace, "route_denied_fact")
            continue
        if not can_access_graph_fact(actor, fact):
            _bump(trace, "policy_denied_fact")
            continue
        if not _fact_is_retrievable(fact):
            _bump(trace, "inactive_or_blocked_fact")
            continue

        citation = _fact_citation(fact)
        if citation is None:
            _bump(trace, "missing_fact_citation")
            continue

        yield {
            "id": fact.fact_id,
            "kind": "memory_graph_fact",
            "fact": {
                "subject_id": fact.subject_id,
                "predicate": fact.predicate,
                "object_id": fact.object_id,
                "subject_type": fact.subject_type,
                "object_type": fact.object_type,
                "confidence": str(fact.confidence),
            },
            "score": _candidate_score(candidate),
            "citation_ids": [citation["id"]],
            "citations": [citation],
            "metadata": _safe_metadata(
                {
                    **_candidate_metadata(candidate),
                    **dict(fact.metadata or {}),
                    "source_code": fact.source_chunk.source_code,
                    "source_object_id": fact.source_chunk.source_object_id,
                    "snapshot_hash": fact.snapshot_hash,
                    "sensitivity": fact.sensitivity,
                }
            ),
        }


def _append_item(item, items, citations_by_id, returned_chunk_ids, returned_fact_ids, limit):
    if len(items) >= limit:
        return
    citations = item.pop("citations")
    if not citations:
        return
    for citation in citations:
        citations_by_id.setdefault(citation["id"], citation)
    if item["kind"] == "memory_chunk":
        returned_chunk_ids.append(item["id"])
    elif item["kind"] == "memory_graph_fact":
        returned_fact_ids.append(item["id"])
    items.append(item)


def _chunks_by_id(chunk_ids):
    ids = [chunk_id for chunk_id in _dedupe(chunk_ids) if chunk_id]
    if not ids:
        return {}
    records = MemoryChunk.objects.select_related("snapshot", "snapshot__source").filter(chunk_id__in=ids)
    by_id = {chunk.chunk_id: chunk for chunk in records}
    return {chunk_id: by_id[chunk_id] for chunk_id in ids if chunk_id in by_id}


def _facts_by_id(fact_ids):
    ids = [fact_id for fact_id in _dedupe(fact_ids) if fact_id]
    if not ids:
        return {}
    records = MemoryGraphFact.objects.select_related("source_chunk", "snapshot", "snapshot__source").filter(fact_id__in=ids)
    by_id = {fact.fact_id: fact for fact in records}
    return {fact_id: by_id[fact_id] for fact_id in ids if fact_id in by_id}


def _chunk_route_allowed(chunk, allowed_sensitivities) -> bool:
    return (
        chunk.sensitivity in allowed_sensitivities
        and route_allows_context_kind(chunk.sensitivity, "retrieved_chunk")
        and route_allows_context_kind(chunk.sensitivity, "citation")
    )


def _fact_route_allowed(fact, allowed_sensitivities) -> bool:
    return (
        fact.sensitivity in allowed_sensitivities
        and route_allows_context_kind(fact.sensitivity, "graph_fact")
        and route_allows_context_kind(fact.sensitivity, "citation")
    )


def _chunk_is_retrievable(chunk: MemoryChunk) -> bool:
    return (
        chunk.is_active
        and chunk.snapshot.is_active
        and chunk.snapshot.status == MemorySnapshot.Status.READY
    )


def _fact_is_retrievable(fact: MemoryGraphFact) -> bool:
    return (
        fact.is_active
        and fact.source_chunk.is_active
        and fact.snapshot.is_active
        and fact.snapshot.status == MemorySnapshot.Status.READY
    )


def _chunk_citation(chunk: MemoryChunk) -> dict | None:
    if not chunk.chunk_id or not chunk.source_code or not chunk.source_object_id or not chunk.snapshot_hash:
        return None
    return {
        "id": f"memory-chunk:{chunk.chunk_id}",
        "kind": "memory_chunk",
        "source_code": chunk.source_code,
        "source_object_id": chunk.source_object_id,
        "chunk_id": chunk.chunk_id,
        "snapshot_hash": chunk.snapshot_hash,
        "position": chunk.position,
        "text_hash": chunk.text_hash,
        "sensitivity": chunk.sensitivity,
    }


def _fact_citation(fact: MemoryGraphFact) -> dict | None:
    chunk = fact.source_chunk
    chunk_id = getattr(chunk, "chunk_id", "")
    if not fact.fact_id or not chunk_id:
        return None
    if not chunk.source_code or not chunk.source_object_id or not fact.snapshot_hash:
        return None
    return {
        "id": f"memory-fact:{fact.fact_id}",
        "kind": "memory_graph_fact",
        "fact_id": fact.fact_id,
        "source_code": chunk.source_code,
        "source_object_id": chunk.source_object_id,
        "chunk_id": chunk_id,
        "snapshot_hash": fact.snapshot_hash,
        "position": chunk.position,
        "text_hash": chunk.text_hash,
        "sensitivity": fact.sensitivity,
    }


def _resolve_safe_text_path(text_path: str) -> Path:
    value = str(text_path or "").strip()
    if not value:
        raise ValidationError("Memory chunk text_path is empty.")

    path = Path(value)
    if path.is_absolute():
        candidates = (path,)
    else:
        candidates = (
            Path(settings.BASE_DIR) / path,
            Path(settings.DATA_DIR) / path,
        )

    safe_root = (Path(settings.DATA_DIR) / "memory" / "safe_corpus").resolve()
    for candidate in candidates:
        resolved = candidate.resolve()
        if _is_relative_to(resolved, safe_root):
            return resolved

    raise ValidationError("Memory chunk text_path is outside the safe corpus.")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_metadata(metadata: Mapping[str, Any]) -> dict:
    safe = {}
    for key, value in dict(metadata or {}).items():
        key_text = str(key)
        if key_text in PATH_METADATA_KEYS or key_text.endswith("_path"):
            continue
        safe[key_text] = value
    return safe


def _candidate_id(candidate, field_name: str) -> str:
    if isinstance(candidate, Mapping):
        value = candidate.get(field_name) or candidate.get("id")
    else:
        value = getattr(candidate, field_name, None) or getattr(candidate, "id", None)
    return str(value or "").strip()


def _candidate_score(candidate) -> float | None:
    if isinstance(candidate, Mapping):
        value = candidate.get("score")
    else:
        value = getattr(candidate, "score", None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_metadata(candidate) -> dict:
    if isinstance(candidate, Mapping):
        metadata = candidate.get("metadata") or {}
    else:
        metadata = getattr(candidate, "metadata", {}) or {}
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _effective_scope_tokens(actor, requested_scope_tokens) -> tuple[str, ...] | None:
    if getattr(actor, "is_superuser", False):
        return _normalize_tokens(requested_scope_tokens)

    actor_tokens = user_scope_tokens(actor)
    if requested_scope_tokens is None:
        return tuple(sorted(actor_tokens))
    requested = set(_normalize_tokens(requested_scope_tokens) or ())
    return tuple(sorted(actor_tokens & requested))


def _normalize_query(query) -> str:
    value = str(query or "").strip()
    if not value:
        raise ValidationError("Memory search query must not be empty.")
    return value


def _normalize_limit(limit) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Memory search limit must be an integer.") from exc
    if value <= 0:
        raise ValidationError("Memory search limit must be positive.")
    if value > MAX_LIMIT:
        raise ValidationError(f"Memory search limit must not exceed {MAX_LIMIT}.")
    return value


def _normalize_tokens(tokens: str | Iterable[str] | None) -> tuple[str, ...] | None:
    if tokens is None:
        return None
    values = (tokens,) if isinstance(tokens, str) else tuple(tokens)
    normalized = []
    seen = set()
    for value in values:
        token = str(value or "").strip()
        if token and token not in seen:
            seen.add(token)
            normalized.append(token)
    return tuple(normalized)


def _assert_actor(actor) -> None:
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "pk", None):
        raise PermissionDenied("Authenticated memory actor is required.")


def _candidate_limit(limit) -> int:
    return min(max(limit * 4, limit, 10), MAX_LIMIT)


def _query_hash(query: str) -> str:
    return "sha256:" + hashlib.sha256(query.encode("utf-8")).hexdigest()


def _audit_denied(*, actor, request_id, query_hash, reason, trace):
    if not getattr(actor, "pk", None):
        return
    record_access_audit(
        actor=actor,
        request_id=request_id,
        query_hash=query_hash,
        policy_decision="denied",
        denied_reason=reason,
        retrieval_trace=trace,
    )


def _bump(trace: dict, key: str) -> None:
    filtered = trace.setdefault("filtered", {})
    filtered[key] = filtered.get(key, 0) + 1


def _dedupe(values):
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            yield value


__all__ = [
    "memory_search",
    "read_safe_chunk_text",
]
