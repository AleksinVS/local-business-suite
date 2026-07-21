from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth.models import Group

from apps.accounts.services import scope_tokens_for_principal


ACL_INHERIT_MODES = {"inherit_source_acl", "inherit_source_acl_with_fallback"}


@dataclass(frozen=True)
class ACLResolution:
    status: str
    scope_tokens: tuple[str, ...] = ()
    fingerprint: str = ""
    reason: str = ""
    raw_principals: tuple[dict[str, Any], ...] = ()
    unresolved_principals: tuple[dict[str, Any], ...] = ()

    @property
    def resolved(self) -> bool:
        return self.status == "resolved" and bool(self.scope_tokens)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scope_tokens": list(self.scope_tokens),
            "fingerprint": self.fingerprint,
            "reason": self.reason,
            "raw_principals": list(self.raw_principals),
            "unresolved_principals": list(self.unresolved_principals),
        }


def resolve_file_acl(*, source, root: Path, file_path: Path, relative_path: str) -> ACLResolution:
    if not getattr(settings, "MEMORY_ACL_INHERITANCE_ENABLED", True):
        return ACLResolution(status="disabled", reason="MEMORY_ACL_INHERITANCE_ENABLED is false")

    metadata = _acl_metadata_from_source_config(source=source, relative_path=relative_path)
    if metadata is None:
        return ACLResolution(status="unreadable", reason="No ACL metadata adapter is configured for this source.")

    allow = _normalize_principals(metadata.get("allow") or metadata.get("principals") or [])
    deny = _normalize_principals(metadata.get("deny") or [])
    fingerprint = _fingerprint({"allow": allow, "deny": deny})
    if deny:
        return ACLResolution(
            status="unresolved",
            reason="Deny ACL entries require explicit review in the MVP.",
            fingerprint=fingerprint,
            raw_principals=tuple(allow + deny),
            unresolved_principals=tuple(deny),
        )

    tokens = set()
    unresolved = []
    for principal in allow:
        mapped = _scope_tokens_for_acl_principal(principal)
        if mapped:
            tokens.update(mapped)
        else:
            unresolved.append(principal)

    if unresolved:
        return ACLResolution(
            status="unresolved",
            reason="One or more ACL principals could not be mapped to portal scope tokens.",
            fingerprint=fingerprint,
            raw_principals=tuple(allow),
            unresolved_principals=tuple(unresolved),
        )
    if not tokens:
        return ACLResolution(
            status="unresolved",
            reason="ACL did not resolve to any portal scope tokens.",
            fingerprint=fingerprint,
            raw_principals=tuple(allow),
        )
    return ACLResolution(
        status="resolved",
        scope_tokens=tuple(sorted(tokens)),
        fingerprint=fingerprint,
        raw_principals=tuple(allow),
    )


def scope_tokens_for_source_object(*, source_object, profile):
    acl = (source_object.metadata or {}).get("acl") or {}
    if profile.acl_mode in ACL_INHERIT_MODES:
        tokens = acl.get("scope_tokens") or []
        if tokens:
            return sorted(set(str(token) for token in tokens if str(token).strip()))
        if profile.acl_mode == "inherit_source_acl_with_fallback" and profile.unresolved_acl_policy == "fallback_scope_rule":
            return scope_tokens_for_source_scope_rule(source_object.source)
        if profile.unresolved_acl_policy == "admin_only":
            return ["role:superuser"]
        return []
    return scope_tokens_for_source_scope_rule(source_object.source)


def acl_blocks_ingestion(*, source_object, profile) -> tuple[bool, str, dict[str, Any]]:
    if profile.acl_mode not in ACL_INHERIT_MODES:
        return False, "", {}

    acl = (source_object.metadata or {}).get("acl") or {}
    if acl.get("status") == "resolved" and acl.get("scope_tokens"):
        return False, "", acl

    if profile.acl_mode == "inherit_source_acl_with_fallback" and profile.unresolved_acl_policy == "fallback_scope_rule":
        fallback = scope_tokens_for_source_scope_rule(source_object.source)
        if fallback:
            return False, "", {**acl, "fallback_scope_tokens": fallback}

    if profile.unresolved_acl_policy == "admin_only":
        return False, "", {**acl, "scope_tokens": ["role:superuser"], "fallback": "admin_only"}

    reason = acl.get("reason") or "Source ACL metadata is unresolved."
    return True, reason, acl


def scope_tokens_for_source_scope_rule(source):
    if source.scope_rule in {"public_knowledge", "authenticated_user", "workorder_visibility", "inventory_visibility"}:
        return ["org:default"]
    tokens = source.config.get("scope_tokens") or []
    if tokens:
        return sorted(set(str(token) for token in tokens if str(token).strip()))
    if source.scope_rule in {"role_scoped", "manual_scope_mapping", "contract_admin"}:
        role_names = source.config.get("role_names") or source.config.get("groups") or []
        existing = Group.objects.filter(name__in=role_names).values_list("name", flat=True)
        return [f"role:{name}" for name in sorted(existing)]
    return []


def _acl_metadata_from_source_config(*, source, relative_path: str):
    config = source.config or {}
    overrides = config.get("acl_overrides") or {}
    if relative_path in overrides:
        return overrides[relative_path]
    default_acl = config.get("default_acl")
    if default_acl:
        return default_acl
    return None


def _scope_tokens_for_acl_principal(principal):
    kind = str(principal.get("kind", "")).lower()
    if kind == "user":
        return scope_tokens_for_principal(
            sid=str(principal.get("sid", "")),
            username=str(principal.get("username", "")),
            domain=str(principal.get("domain", "")),
        )
    if kind == "group":
        name = str(principal.get("name", ""))
        if name and Group.objects.filter(name=name).exists():
            return {f"role:{name}"}
    return set()


def _normalize_principals(values):
    principals = []
    for value in values:
        if isinstance(value, dict):
            principals.append({str(key): str(item) for key, item in value.items()})
    return principals


def _fingerprint(payload):
    import json

    data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()
