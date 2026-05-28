from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError

from .knowledge_files import read_knowledge_item_file
from .models import MemorySearchDocument, MemorySourceObject
from .policies import (
    can_access_search_document,
    effective_source_trust,
    search_document_scope_tokens,
    search_document_sensitivity,
    search_document_source,
    source_allows_direct_context,
    user_scope_tokens,
)
from .routing import resolve_retrieval_route, route_allows_context_kind
from .services import record_access_audit
from .vector_backends import get_default_backend, get_default_vector_backend


DEFAULT_LIMIT = 5
MAX_LIMIT = 50
PATH_METADATA_KEYS = {"raw_path", "safe_path", "text_path", "path"}
RRF_K = 60

DEFAULT_RANKING_PROFILES = {
    "precise": {
        "fusion": "rrf",
        "fulltext_weight": 0.90,
        "vector_weight": 0.10,
        "graph_weight": 0.00,
        "overlap_boost": 0.08,
    },
    "balanced": {
        "fusion": "rrf",
        "fulltext_weight": 0.55,
        "vector_weight": 0.45,
        "graph_weight": 0.00,
        "overlap_boost": 0.10,
    },
    "semantic_heavy": {
        "fusion": "rrf",
        "fulltext_weight": 0.25,
        "vector_weight": 0.75,
        "graph_weight": 0.00,
        "overlap_boost": 0.10,
    },
    "source_content": {
        "fusion": "rrf",
        "fulltext_weight": 0.70,
        "vector_weight": 0.30,
        "graph_weight": 0.00,
        "overlap_boost": 0.10,
    },
    "source_semantic": {
        "fusion": "rrf",
        "fulltext_weight": 0.30,
        "vector_weight": 0.70,
        "graph_weight": 0.00,
        "overlap_boost": 0.10,
    },
    "graph_future": {
        "fusion": "rrf",
        "fulltext_weight": 0.35,
        "vector_weight": 0.35,
        "graph_weight": 0.30,
        "overlap_boost": 0.10,
    },
}

DEFAULT_PROFILE_BY_SEARCH_MODE = {
    "knowledge_default": "balanced",
    "knowledge_precise": "precise",
    "knowledge_semantic": "semantic_heavy",
    "knowledge_graph": "graph_future",
    "source_explicit": "source_content",
    "source_fallback": "balanced",
}


def memory_search(
    actor,
    query,
    scope_tokens=None,
    sensitivity=None,
    limit=DEFAULT_LIMIT,
    vector_backend=None,
    graph_backend=None,
    request_id="",
    trusted_context_only=True,
    search_mode="knowledge_default",
    include_source_data=False,
    ranking_profile="",
    source_codes=None,
):
    query_text = _normalize_query(query)
    query_hash = _query_hash(query_text)
    normalized_limit = _normalize_limit(limit)
    normalized_search_mode = _normalize_search_mode(search_mode)
    normalized_ranking_profile, ranking_profile_config = _resolve_ranking_profile(ranking_profile, normalized_search_mode)
    allowed_corpus_types = _allowed_corpus_types(normalized_search_mode)
    allowed_source_codes = _normalize_tokens(source_codes)
    trace: dict[str, Any] = {
        "filtered": {},
        "search_mode": normalized_search_mode,
        "ranking_profile": normalized_ranking_profile,
        "ranking_profile_config": _public_profile_config(ranking_profile_config),
        "search_channels": _search_channel_trace(normalized_search_mode, ranking_profile_config),
        "source_codes": list(allowed_source_codes or []),
    }

    try:
        _assert_actor(actor)
        route_decision = resolve_retrieval_route(sensitivity)
        trace["route"] = route_decision.as_trace()

        effective_scope_tokens = _effective_scope_tokens(actor, scope_tokens)
        fulltext_candidates = _annotate_candidate_ranks(
            _search_fulltext_candidates(
                fulltext_backend=vector_backend,
                query=query_text,
                scope_tokens=effective_scope_tokens,
                sensitivity=route_decision.allowed_sensitivities,
                limit=normalized_limit,
            ),
            channel="fulltext",
        )
        vector_candidates = _annotate_candidate_ranks(
            _search_vector_candidates(
                search_mode=normalized_search_mode,
                ranking_profile_config=ranking_profile_config,
                query=query_text,
                scope_tokens=effective_scope_tokens,
                sensitivity=route_decision.allowed_sensitivities,
                limit=normalized_limit,
                allowed_corpus_types=allowed_corpus_types,
            ),
            channel="vector",
        )
        graph_candidates = _search_graph_candidates(
            graph_backend=graph_backend,
            actor=actor,
            query=query_text,
            scope_tokens=effective_scope_tokens,
            sensitivity=route_decision.allowed_sensitivities,
            limit=normalized_limit,
        )
        _update_search_channel_trace(trace, fulltext_candidates=fulltext_candidates, vector_candidates=vector_candidates)
        trace["candidate_counts"] = {
            "fulltext": len(fulltext_candidates),
            "vector": len(vector_candidates),
            "graph": len(graph_candidates),
        }

        citations_by_id: dict[str, dict] = {}
        candidate_items = []
        items = []
        returned_document_ids: list[str] = []
        returned_fact_ids: list[str] = []

        for item in _document_items(
            actor=actor,
            candidates=[*fulltext_candidates, *vector_candidates],
            allowed_sensitivities=route_decision.allowed_sensitivities,
            trace=trace,
            trusted_context_only=trusted_context_only,
            allowed_corpus_types=allowed_corpus_types,
            allowed_source_codes=set(allowed_source_codes or ()),
        ):
            candidate_items.append(item)

        for item in graph_candidates:
            candidate_items.append(item)

        ranked_items = _rank_and_pack_items(
            candidate_items,
            limit=normalized_limit,
            trace=trace,
            ranking_profile=normalized_ranking_profile,
            ranking_profile_config=ranking_profile_config,
        )
        for item in ranked_items:
            _append_item(item, items, citations_by_id, returned_document_ids, returned_fact_ids, normalized_limit)

        if len(items) == 0 and _source_data_fallback_allowed(normalized_search_mode, include_source_data):
            for item in _source_data_fallback_items(
                actor=actor,
                query=query_text,
                allowed_sensitivities=route_decision.allowed_sensitivities,
                limit=normalized_limit,
                trace=trace,
                allowed_source_codes=set(allowed_source_codes or ()),
            ):
                items.append(item)
                returned_document_ids.append(str(item.get("id", "")))
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
                "trusted_context_only": trusted_context_only,
                "search_mode": normalized_search_mode,
                "ranking_profile": normalized_ranking_profile,
                "ranking_profile_config": _public_profile_config(ranking_profile_config),
                "corpus_types": sorted(allowed_corpus_types),
                "search_channels": trace["search_channels"],
            },
        }
        trace["returned_count"] = len(items)
        trace["citation_count"] = len(citations)
        trace["returned_document_ids"] = returned_document_ids
        record_access_audit(
            actor=actor,
            request_id=request_id,
            query_hash=query_hash,
            returned_document_ids=returned_document_ids,
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

def read_search_document_text(document: MemorySearchDocument, *, actor=None) -> str:
    if document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE:
        if document.knowledge_item_id is None:
            raise ValidationError("Knowledge search document has no knowledge item.")
        return read_knowledge_item_file(document.knowledge_item).body
    if document.source_object_id:
        from .services import render_source_object_text

        rendered = render_source_object_text(document.source_object, actor=actor)
        if rendered:
            return rendered
        return document.source_object.file_name or document.source_object.relative_path or document.source_object.object_id
    return ""


def _search_fulltext_candidates(*, fulltext_backend, query, scope_tokens, sensitivity, limit):
    backend = fulltext_backend or get_default_backend()
    if backend is None:
        return []
    if not hasattr(backend, "search"):
        raise ValidationError("Memory search backend must provide search().")
    return list(
        backend.search(
            query,
            scope_tokens=scope_tokens,
            sensitivity=sensitivity,
            limit=_candidate_limit(limit),
        )
    )


def _annotate_candidate_ranks(candidates, *, channel: str):
    annotated = []
    for rank, candidate in enumerate(candidates, start=1):
        metadata = _candidate_metadata(candidate)
        metadata["search_channel"] = channel
        metadata["raw_score"] = _candidate_score(candidate)
        metadata["channel_rank"] = rank
        metadata["rrf_score"] = _rrf_score(rank)
        if isinstance(candidate, Mapping):
            item = dict(candidate)
            item["metadata"] = metadata
            annotated.append(item)
            continue
        annotated.append(
            {
                "document_id": _candidate_id(candidate, "document_id"),
                "score": _candidate_score(candidate),
                "metadata": metadata,
            }
        )
    return annotated


def _search_vector_candidates(*, search_mode, ranking_profile_config, query, scope_tokens, sensitivity, limit, allowed_corpus_types):
    if not _vector_search_requested(search_mode, ranking_profile_config):
        return []
    backend = get_default_vector_backend()
    if backend is None:
        return []
    if not hasattr(backend, "search"):
        raise ValidationError("Memory vector backend must provide search().")
    candidates = list(
        backend.search(
            query,
            scope_tokens=scope_tokens,
            sensitivity=sensitivity,
            limit=_candidate_limit(limit),
        )
    )
    return [
        candidate
        for candidate in candidates
        if (_candidate_metadata(candidate).get("corpus_type") or "") in allowed_corpus_types
    ]


def _search_graph_candidates(*, graph_backend, actor, query, scope_tokens, sensitivity, limit):
    if graph_backend is None:
        return []
    if not hasattr(graph_backend, "search_facts"):
        return []
    # Графовый поиск будет перепривязан к MemorySearchDocument отдельным блоком.
    return []


def _rank_and_pack_items(items, *, limit, trace, ranking_profile, ranking_profile_config):
    budget = _retrieval_budget()
    context_budget = budget.get("context_packing", {})
    max_items = min(limit, int(context_budget.get("max_items", limit) or limit))
    max_tokens = int(context_budget.get("max_tokens", 1200) or 1200)
    max_items_per_source = int(context_budget.get("max_items_per_source", 2) or 2)
    fusion = budget.get("rank_fusion", {})

    merged_items = _merge_candidate_items(items)
    ranked = []
    for index, item in enumerate(merged_items):
        score = _rank_score(item, fusion=fusion, ranking_profile_config=ranking_profile_config)
        ranked.append((score, index, item))
    ranked.sort(key=lambda value: (-value[0], value[1]))

    packed = []
    source_counts: dict[str, int] = {}
    token_count = 0
    for score, _index, item in ranked:
        source_key = _item_source_key(item)
        if source_key:
            count = source_counts.get(source_key, 0)
            if count >= max_items_per_source:
                _bump(trace, "context_pack_diversity_denied")
                continue
            source_counts[source_key] = count + 1
        estimated_tokens = _estimate_tokens(_item_text(item))
        if packed and token_count + estimated_tokens > max_tokens:
            _bump(trace, "context_pack_token_budget_denied")
            continue
        item["score"] = score
        packed.append(item)
        token_count += estimated_tokens
        if len(packed) >= max_items:
            break

    trace["rank_fusion"] = {
        "profile": ranking_profile,
        "normalization": ranking_profile_config.get("fusion", "rrf"),
        "weights": {
            "fulltext": float(ranking_profile_config.get("fulltext_weight", 0) or 0),
            "vector": float(ranking_profile_config.get("vector_weight", 0) or 0),
            "graph": float(ranking_profile_config.get("graph_weight", 0) or 0),
        },
        "rrf_k": int(ranking_profile_config.get("rrf_k", RRF_K) or RRF_K),
        "input_count": len(items),
        "merged_count": len(merged_items),
        "packed_count": len(packed),
        "max_items": max_items,
        "max_tokens": max_tokens,
        "estimated_tokens": token_count,
        "llm_used": False,
    }
    return packed


def _merge_candidate_items(items):
    by_id: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    for item in items:
        item_id = str(item.get("id") or "")
        if not item_id:
            continue
        metadata = dict(item.get("metadata") or {})
        channel = metadata.get("search_channel") or metadata.get("search_backend") or "unknown"
        channel_score = _channel_score_payload(metadata, item.get("score"))
        if item_id not in by_id:
            item["metadata"] = {
                **metadata,
                "search_channels_matched": [channel],
                "channel_scores": {channel: channel_score},
            }
            by_id[item_id] = item
            ordered_ids.append(item_id)
            continue
        existing = by_id[item_id]
        existing_metadata = dict(existing.get("metadata") or {})
        channels = list(existing_metadata.get("search_channels_matched") or [])
        if channel not in channels:
            channels.append(channel)
        channel_scores = dict(existing_metadata.get("channel_scores") or {})
        channel_scores[channel] = channel_score
        existing["metadata"] = {
            **metadata,
            **existing_metadata,
            "search_channels_matched": channels,
            "channel_scores": channel_scores,
        }
    return [by_id[item_id] for item_id in ordered_ids]


def _document_items(*, actor, candidates, allowed_sensitivities, trace, trusted_context_only, allowed_corpus_types, allowed_source_codes):
    document_ids = [_candidate_id(candidate, "document_id") for candidate in candidates]
    documents = _documents_by_id(document_ids)

    for candidate in candidates:
        document_id = _candidate_id(candidate, "document_id")
        document = documents.get(document_id)
        if document is None:
            _bump(trace, "missing_document")
            continue
        if not _document_route_allowed(document, allowed_sensitivities):
            _bump(trace, "route_denied_document")
            continue
        if not can_access_search_document(actor, document):
            _bump(trace, "policy_denied_document")
            continue
        if not _document_is_retrievable(document):
            _bump(trace, "inactive_or_blocked_document")
            continue
        if document.corpus_type not in allowed_corpus_types:
            _bump(trace, "corpus_denied_document")
            continue

        source = search_document_source(document)
        if allowed_source_codes and _document_source_code(document, source=source) not in allowed_source_codes:
            _bump(trace, "source_code_denied_document")
            continue
        trust_decision = effective_source_trust(source)
        if trusted_context_only and not source_allows_direct_context(source, "retrieved_chunk"):
            _bump(trace, "trust_gate_denied_document")
            continue

        citation = _document_citation(document, trust_decision=trust_decision)
        if citation is None:
            _bump(trace, "missing_document_citation")
            continue
        try:
            text = read_search_document_text(document, actor=actor)
        except (OSError, ValidationError):
            _bump(trace, "unsafe_or_missing_document_text")
            continue

        is_knowledge = document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE
        metadata = _safe_metadata(
            {
                **_candidate_metadata(candidate),
                **dict(document.metadata or {}),
                "corpus_type": document.corpus_type,
                "source_code": _document_source_code(document, source=source),
                "source_kind": _document_source_kind(document, source=source),
                "source_object_id": _document_source_object_id(document),
                "sensitivity": search_document_sensitivity(document),
                "trust_status": trust_decision.trust_status,
                "authority_class": trust_decision.authority_class,
                "trusted_for_context": trust_decision.trusted_for_context,
                "index_status": document.index_status,
                "accepted_knowledge": is_knowledge,
            }
        )
        item = {
            "id": document.document_id,
            "kind": "knowledge" if is_knowledge else "source_data",
            "result_type": "knowledge" if is_knowledge else "source_data",
            "knowledge_id": document.knowledge_item.memory_id if is_knowledge and document.knowledge_item_id else "",
            "text": text,
            "score": _candidate_score(candidate),
            "citation_ids": [citation["id"]],
            "citations": [citation],
            "source_refs": _document_source_refs(document),
            "source_object_id": _document_source_object_id(document),
            "source_uri": _document_source_uri(document),
            "source_kind": _document_source_kind(document, source=source),
            "source_code": _document_source_code(document, source=source),
            "index_status": document.index_status,
            "metadata": metadata,
        }
        if not is_knowledge:
            item["warning"] = "Это исходный объект, а не принятое знание."
        yield item


def _append_item(item, items, citations_by_id, returned_document_ids, returned_fact_ids, limit):
    if len(items) >= limit:
        return
    citations = item.pop("citations", [])
    for citation in citations:
        citations_by_id.setdefault(citation["id"], citation)
    if item["kind"] in {"knowledge", "source_data"}:
        returned_document_ids.append(item["id"])
    elif item["kind"] == "memory_graph_fact":
        returned_fact_ids.append(item["id"])
    items.append(item)


def _documents_by_id(document_ids):
    ids = [document_id for document_id in _dedupe(document_ids) if document_id]
    if not ids:
        return {}
    records = (
        MemorySearchDocument.objects.select_related("knowledge_item", "source_object", "source_object__source")
        .filter(document_id__in=ids)
    )
    by_id = {document.document_id: document for document in records}
    return {document_id: by_id[document_id] for document_id in ids if document_id in by_id}


def _document_route_allowed(document: MemorySearchDocument, allowed_sensitivities) -> bool:
    sensitivity = search_document_sensitivity(document)
    return (
        sensitivity in allowed_sensitivities
        and route_allows_context_kind(sensitivity, "retrieved_chunk")
        and route_allows_context_kind(sensitivity, "citation")
    )


def _document_is_retrievable(document: MemorySearchDocument) -> bool:
    return document.index_status == MemorySearchDocument.IndexStatus.READY


def _document_citation(document: MemorySearchDocument, *, trust_decision) -> dict | None:
    source_code = _document_source_code(document)
    if not document.document_id or not source_code:
        return None
    return {
        "id": f"memory-document:{document.document_id}",
        "kind": "knowledge" if document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE else "source_data",
        "result_type": "knowledge" if document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE else "source_data",
        "document_id": document.document_id,
        "knowledge_id": document.knowledge_item.memory_id if document.knowledge_item_id else "",
        "source_code": source_code,
        "source_kind": _document_source_kind(document),
        "source_object_id": _document_source_object_id(document),
        "source_refs": _document_source_refs(document),
        "body_hash": document.body_hash,
        "sensitivity": search_document_sensitivity(document),
        "trust_status": trust_decision.trust_status,
        "authority_class": trust_decision.authority_class,
        "trusted_for_context": trust_decision.trusted_for_context,
    }


def _normalize_search_mode(value) -> str:
    mode = str(value or "knowledge_default").strip()
    allowed = {
        "knowledge_default",
        "knowledge_precise",
        "knowledge_semantic",
        "knowledge_graph",
        "source_explicit",
        "source_fallback",
    }
    if mode not in allowed:
        raise ValidationError("Unsupported memory search mode.")
    return mode


def _resolve_ranking_profile(value, search_mode: str) -> tuple[str, dict[str, Any]]:
    profile_id = str(value or "").strip() or DEFAULT_PROFILE_BY_SEARCH_MODE[search_mode]
    profiles = _ranking_profiles()
    if profile_id not in profiles:
        raise ValidationError("Unsupported memory ranking profile.")
    profile = {**DEFAULT_RANKING_PROFILES.get(profile_id, {}), **dict(profiles[profile_id] or {})}
    profile.setdefault("fusion", "rrf")
    profile.setdefault("rrf_k", RRF_K)
    profile.setdefault("overlap_boost", DEFAULT_RANKING_PROFILES.get(profile_id, {}).get("overlap_boost", 0.0))
    if profile.get("fusion") != "rrf":
        raise ValidationError("Only rrf memory ranking fusion is supported in this runtime.")
    return profile_id, profile


def _ranking_profiles() -> dict[str, dict[str, Any]]:
    configured = dict((getattr(settings, "LOCAL_BUSINESS_MEMORY_PROFILES", {}) or {}).get("ranking_profiles", {}) or {})
    profiles = {key: dict(value) for key, value in DEFAULT_RANKING_PROFILES.items()}
    for key, value in configured.items():
        profiles[key] = {**profiles.get(key, {}), **dict(value or {})}
    return profiles


def _public_profile_config(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "fusion": str(profile.get("fusion") or "rrf"),
        "weights": {
            "fulltext": float(profile.get("fulltext_weight", 0) or 0),
            "vector": float(profile.get("vector_weight", 0) or 0),
            "graph": float(profile.get("graph_weight", 0) or 0),
        },
        "overlap_boost": float(profile.get("overlap_boost", 0) or 0),
    }


def _vector_search_requested(search_mode: str, ranking_profile_config: Mapping[str, Any]) -> bool:
    if float(ranking_profile_config.get("vector_weight", 0) or 0) <= 0:
        return False
    return search_mode in {
        "knowledge_default",
        "knowledge_precise",
        "knowledge_semantic",
        "knowledge_graph",
        "source_explicit",
        "source_fallback",
    }


def _search_channel_trace(search_mode: str, ranking_profile_config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    vector_requested = _vector_search_requested(search_mode, ranking_profile_config)
    return {
        "document_index": {
            "status": "enabled",
            "implementation": "memory_search_document",
            "stores_retrievable_text": False,
        },
        "fulltext": {
            "status": "enabled",
            "implementation": "sqlite_fts5_with_token_fallback",
            "prefix_search_used": False,
            "token_fallback_used": False,
        },
        "vector": {
            "status": "enabled" if vector_requested else "available",
            "implementation": "lancedb",
            "requested": vector_requested,
        },
        "graph": {
            "status": "disabled",
            "reason": "Graph runtime search not_ready; схема и extraction остаются отдельным контуром.",
            "requested": search_mode == "knowledge_graph",
        },
    }


def _update_search_channel_trace(trace: dict[str, Any], *, fulltext_candidates, vector_candidates) -> None:
    search_channels = trace.setdefault("search_channels", {})
    fulltext = search_channels.setdefault("fulltext", {})
    fulltext["candidate_count"] = len(fulltext_candidates)
    fulltext["prefix_search_used"] = any(bool((_candidate_metadata(candidate)).get("prefix_search_used")) for candidate in fulltext_candidates)
    fulltext["token_fallback_used"] = any(bool((_candidate_metadata(candidate)).get("token_fallback_used")) for candidate in fulltext_candidates)
    fulltext["fts5_enabled"] = any(bool((_candidate_metadata(candidate)).get("fts5_enabled")) for candidate in fulltext_candidates)
    vector = search_channels.setdefault("vector", {})
    vector["candidate_count"] = len(vector_candidates)
    if vector_candidates:
        metadata = _candidate_metadata(vector_candidates[0])
        vector["status"] = "enabled"
        vector["embedding_model"] = metadata.get("embedding_model", "")
        vector["embedding_version"] = metadata.get("embedding_version", "")
        vector["embedding_profile"] = metadata.get("embedding_profile", "")


def _allowed_corpus_types(search_mode: str) -> set[str]:
    if search_mode == "source_explicit":
        return {"source_data"}
    if search_mode == "source_fallback":
        return {"knowledge", "source_data"}
    return {"knowledge"}


def _source_data_fallback_allowed(search_mode: str, include_source_data: bool) -> bool:
    return bool(include_source_data or search_mode in {"knowledge_default", "source_fallback", "source_explicit"})


def _source_data_fallback_items(*, actor, query, allowed_sensitivities, limit, trace, allowed_source_codes):
    terms = _query_terms(query)
    if not terms:
        return []
    queryset = MemorySourceObject.objects.select_related("source").filter(source__status="enabled")
    if allowed_source_codes:
        queryset = queryset.filter(source__code__in=allowed_source_codes)
    if allowed_sensitivities:
        queryset = queryset.filter(source__sensitivity__in=allowed_sensitivities)
    items = []
    actor_tokens = user_scope_tokens(actor)
    for source_object in queryset.order_by("-last_seen_at", "id")[:200]:
        haystack = " ".join(
            [
                source_object.file_name,
                source_object.relative_path,
                source_object.object_uri,
                source_object.object_id,
            ]
        ).lower()
        if not all(term.lower() in haystack for term in terms[:3]):
            continue
        object_tokens = set((source_object.metadata or {}).get("scope_tokens") or [])
        if object_tokens and not object_tokens & actor_tokens and not getattr(actor, "is_superuser", False):
            _bump(trace, "source_data_scope_denied")
            continue
        if not object_tokens and not getattr(actor, "is_superuser", False):
            _bump(trace, "source_data_missing_scope")
            continue
        from .services import can_access_source_object_via_adapter

        if not can_access_source_object_via_adapter(actor, source_object):
            _bump(trace, "source_data_adapter_denied")
            continue
        document = _source_object_document(source_object)
        items.append(
            {
                "id": document.document_id,
                "kind": "source_data",
                "result_type": "source_data",
                "source_object_id": source_object.object_id,
                "source_uri": source_object.object_uri,
                "source_kind": source_object.source.source_kind,
                "source_code": source_object.source.code,
                "index_status": document.index_status,
                "warning": "Это исходный объект, а не принятое знание.",
                "metadata": _safe_metadata(
                    {
                        "file_name": source_object.file_name,
                        "relative_path": source_object.relative_path,
                        "content_hash": source_object.content_hash,
                        "sensitivity": source_object.source.sensitivity,
                        "corpus_type": "source_data",
                    }
                ),
            }
        )
        if len(items) >= limit:
            break
    trace["source_data_fallback_count"] = len(items)
    return items


def _source_object_document(source_object: MemorySourceObject) -> MemorySearchDocument:
    document_id = "source:" + hashlib.sha256(f"{source_object.source.code}:{source_object.object_id}".encode("utf-8")).hexdigest()[:40]
    document, _ = MemorySearchDocument.objects.get_or_create(
        document_id=document_id,
        defaults={
            "corpus_type": MemorySearchDocument.CorpusType.SOURCE_DATA,
            "object_kind": MemorySearchDocument.ObjectKind.SOURCE_OBJECT,
            "source_object": source_object,
            "body_hash": source_object.content_hash,
            "index_status": MemorySearchDocument.IndexStatus.READY,
            "metadata": {
                "file_name": source_object.file_name,
                "relative_path": source_object.relative_path,
                "content_hash": source_object.content_hash,
            },
        },
    )
    return document


def _document_source_code(document: MemorySearchDocument, *, source=None) -> str:
    if document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE and document.knowledge_item_id:
        return document.knowledge_item.source_code
    source = source or search_document_source(document)
    return source.code if source is not None else ""


def _document_source_kind(document: MemorySearchDocument, *, source=None) -> str:
    if document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE and document.knowledge_item_id:
        return document.knowledge_item.source_kind
    source = source or search_document_source(document)
    return source.source_kind if source is not None else ""


def _document_source_object_id(document: MemorySearchDocument) -> str:
    if document.source_object_id:
        return document.source_object.object_id
    if document.knowledge_item_id:
        return document.knowledge_item.memory_id
    return ""


def _document_source_uri(document: MemorySearchDocument) -> str:
    if document.source_object_id:
        return document.source_object.object_uri
    if document.knowledge_item_id:
        return f"knowledge_repo:{document.knowledge_item.knowledge_file_path}"
    return ""


def _document_source_refs(document: MemorySearchDocument) -> list[dict]:
    if document.corpus_type == MemorySearchDocument.CorpusType.KNOWLEDGE and document.knowledge_item_id:
        return list(document.knowledge_item.source_refs or [])
    if document.source_object_id:
        return [{"kind": "source_object", "value": document.source_object.object_id}]
    return []


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


def _rank_score(item: Mapping[str, Any], *, fusion: Mapping[str, Any], ranking_profile_config: Mapping[str, Any]) -> float:
    metadata = item.get("metadata") or {}
    channel_scores = metadata.get("channel_scores") or {}
    score = 0.0
    for channel, weight_key in (
        ("fulltext", "fulltext_weight"),
        ("vector", "vector_weight"),
        ("graph", "graph_weight"),
    ):
        payload = channel_scores.get(channel) or {}
        try:
            rrf_score = float(payload.get("rrf_score") or 0)
        except (TypeError, ValueError):
            rrf_score = 0.0
        score += float(ranking_profile_config.get(weight_key, 0) or 0) * rrf_score
    if len(channel_scores) > 1:
        score += float(ranking_profile_config.get("overlap_boost", 0) or 0)

    authority_class = metadata.get("authority_class")
    if authority_class in {"system_of_record", "approved_corpus", "reviewed_org_knowledge", "approved_user_memory"}:
        score += float(fusion.get("authority_boost", 0.25) or 0)
    try:
        confidence = float(metadata.get("confidence", 1))
    except (TypeError, ValueError):
        confidence = 1
    if confidence < 0.5:
        score -= float(fusion.get("low_confidence_penalty", 0.25) or 0)
    return max(score, 0.0)


def _channel_score_payload(metadata: Mapping[str, Any], fallback_score) -> dict[str, Any]:
    raw_score = metadata.get("raw_score")
    if raw_score is None:
        raw_score = fallback_score
    try:
        raw_score = float(raw_score) if raw_score is not None else None
    except (TypeError, ValueError):
        raw_score = None
    rank = metadata.get("channel_rank")
    try:
        rank = int(rank) if rank is not None else None
    except (TypeError, ValueError):
        rank = None
    rrf_score = metadata.get("rrf_score")
    try:
        rrf_score = float(rrf_score) if rrf_score is not None else (_rrf_score(rank) if rank else 0.0)
    except (TypeError, ValueError):
        rrf_score = 0.0
    return {
        "raw_score": raw_score,
        "rank": rank,
        "rrf_score": rrf_score,
    }


def _rrf_score(rank: int, *, k: int = RRF_K) -> float:
    try:
        value = int(rank)
    except (TypeError, ValueError):
        return 0.0
    if value <= 0:
        return 0.0
    return 1.0 / (k + value)


def _item_source_key(item: Mapping[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    return str(metadata.get("source_code") or item.get("kind") or "")


def _item_text(item: Mapping[str, Any]) -> str:
    return str(item.get("text") or "")


def _estimate_tokens(text: str) -> int:
    value = str(text or "").strip()
    if not value:
        return 0
    return max(1, len(value) // 4)


def _retrieval_budget() -> dict:
    return dict(getattr(settings, "LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET", {}) or {})


def _query_terms(query: str) -> tuple[str, ...]:
    return tuple(term for term in str(query or "").lower().split() if len(term) >= 3)[:8]


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
    "read_search_document_text",
]
