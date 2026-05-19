from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError


RETRIEVAL_CONTEXT_KINDS = frozenset({"retrieved_chunk", "citation", "graph_fact"})
FALLBACK_SENSITIVITY_LEVELS = (
    "public",
    "internal",
    "confidential",
    "pii_redacted",
    "pii_original",
    "secret",
)
FALLBACK_DEFAULT_ROUTE = "internal"


@dataclass(frozen=True)
class MemoryRouteDecision:
    requested_sensitivities: tuple[str, ...]
    allowed_sensitivities: tuple[str, ...]
    default_route: str
    routes: dict[str, dict]

    def as_trace(self) -> dict:
        return {
            "requested_sensitivities": list(self.requested_sensitivities),
            "allowed_sensitivities": list(self.allowed_sensitivities),
            "default_route": self.default_route,
            "mode": "local",
        }


def resolve_retrieval_route(sensitivity: str | Iterable[str] | None = None) -> MemoryRouteDecision:
    payload = _routing_payload()
    levels = tuple(payload.get("sensitivity_levels") or FALLBACK_SENSITIVITY_LEVELS)
    routes = payload.get("routes") or {}
    default_route = payload.get("default_route") or FALLBACK_DEFAULT_ROUTE

    requested = _normalize_sensitivities(sensitivity)
    if requested is None:
        requested = (default_route,)
    if not requested:
        raise ValidationError("At least one memory sensitivity level is required.")

    unknown = sorted(set(requested) - set(levels))
    if unknown:
        raise ValidationError("Unknown memory sensitivity level: " + ", ".join(unknown) + ".")

    denied = tuple(level for level in requested if not _route_allows_retrieval(routes.get(level, {})))
    if denied:
        reasons = [_denial_reason(level, routes.get(level, {})) for level in denied]
        raise PermissionDenied("; ".join(reason for reason in reasons if reason))

    return MemoryRouteDecision(
        requested_sensitivities=tuple(requested),
        allowed_sensitivities=tuple(requested),
        default_route=default_route,
        routes={level: dict(routes.get(level, {})) for level in requested},
    )


def route_allows_context_kind(sensitivity: str, context_kind: str) -> bool:
    route = (_routing_payload().get("routes") or {}).get(sensitivity, {})
    return context_kind in set(route.get("allowed_context_kinds") or [])


def _routing_payload() -> dict:
    payload = getattr(settings, "LOCAL_BUSINESS_MEMORY_ROUTING", None)
    if isinstance(payload, dict) and payload:
        return payload
    return {
        "sensitivity_levels": list(FALLBACK_SENSITIVITY_LEVELS),
        "default_route": FALLBACK_DEFAULT_ROUTE,
        "routes": {
            "public": _fallback_allowed_route(),
            "internal": _fallback_allowed_route(),
            "confidential": _fallback_allowed_route(cloud_allowed=False),
            "pii_redacted": _fallback_allowed_route(cloud_allowed=False),
            "pii_original": _fallback_denied_route("Original PII must not be assembled into memory context."),
            "secret": _fallback_denied_route("Secrets are not valid memory context."),
        },
    }


def _normalize_sensitivities(sensitivity: str | Iterable[str] | None) -> tuple[str, ...] | None:
    if sensitivity is None:
        return None
    values = (sensitivity,) if isinstance(sensitivity, str) else tuple(sensitivity)
    normalized = []
    seen = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            normalized.append(item)
    return tuple(normalized)


def _route_allows_retrieval(route: dict) -> bool:
    if route.get("default_llm") == "deny":
        return False
    allowed_context = set(route.get("allowed_context_kinds") or [])
    return {"citation", "retrieved_chunk"}.issubset(allowed_context) or {"citation", "graph_fact"}.issubset(allowed_context)


def _denial_reason(level: str, route: dict) -> str:
    return route.get("denial_reason") or f"Memory sensitivity '{level}' is not allowed for retrieval."


def _fallback_allowed_route(*, cloud_allowed=True) -> dict:
    return {
        "default_llm": "local",
        "cloud_allowed": cloud_allowed,
        "requires_redaction": True,
        "allow_original_pii": False,
        "allowed_context_kinds": ["question", "retrieved_chunk", "citation", "metadata", "graph_fact"],
        "denial_reason": None,
    }


def _fallback_denied_route(reason: str) -> dict:
    return {
        "default_llm": "deny",
        "cloud_allowed": False,
        "requires_redaction": True,
        "allow_original_pii": False,
        "allowed_context_kinds": [],
        "denial_reason": reason,
    }


__all__ = [
    "MemoryRouteDecision",
    "resolve_retrieval_route",
    "route_allows_context_kind",
]
