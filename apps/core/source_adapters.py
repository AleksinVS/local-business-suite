from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from django.core.exceptions import ValidationError
from django.utils import timezone


SCHEMA_VERSION = "source-object-envelope-v1"
OPERATION_UPSERT = "upsert"
OPERATION_DELETE = "delete"
SOURCE_ORIGIN_INTERNAL = "internal"
SOURCE_ORIGIN_EXTERNAL = "external"
ACCESS_MODE_SCOPE_TOKENS = "scope_tokens"
ACCESS_MODE_ACL_INHERITED = "acl_inherited"
ACCESS_MODE_MANUAL_MAPPING = "manual_mapping"
ACCESS_MODE_ADAPTER_CHECK = "adapter_check"


@dataclass(frozen=True)
class PrivacyProfile:
    profile_id: str
    enabled: bool
    detect: bool
    redact_before_index: bool
    audit: bool
    block: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "enabled": self.enabled,
            "detect": self.detect,
            "redact_before_index": self.redact_before_index,
            "audit": self.audit,
            "block": self.block,
        }


PRIVACY_PROFILES: dict[str, PrivacyProfile] = {
    "pii_off": PrivacyProfile(
        profile_id="pii_off",
        enabled=False,
        detect=False,
        redact_before_index=False,
        audit=False,
        block=False,
    ),
    "pii_guarded": PrivacyProfile(
        profile_id="pii_guarded",
        enabled=True,
        detect=True,
        redact_before_index=True,
        audit=True,
        block=False,
    ),
    "pii_strict": PrivacyProfile(
        profile_id="pii_strict",
        enabled=True,
        detect=True,
        redact_before_index=True,
        audit=True,
        block=True,
    ),
}

LEGACY_PII_POLICY_TO_PROFILE = {
    "": "",
    "no_pii_expected": "pii_off",
    "reject_pii": "pii_strict",
    "deidentify_before_index": "pii_guarded",
    "allow_redacted_only": "pii_guarded",
    "pii_off": "pii_off",
    "pii_guarded": "pii_guarded",
    "pii_strict": "pii_strict",
}

EXTERNAL_SOURCE_KINDS = {"external_api", "external_api_snapshot", "email_imap", "file_drop"}
INTERNAL_SOURCE_KINDS = {"django_model", "local_path", "unc_path", "documentation", "contract_file", "synthetic_fixture"}


@dataclass(frozen=True)
class SourceObjectEnvelope:
    source_code: str
    source_origin: str
    source_kind: str
    domain: str
    object_type: str
    object_id: str
    title: str
    text: str
    content_hash: str
    schema_version: str = SCHEMA_VERSION
    envelope_id: str = ""
    operation: str = OPERATION_UPSERT
    payload: Mapping[str, Any] = field(default_factory=dict)
    relations: tuple[Mapping[str, Any], ...] = ()
    previous_content_hash: str = ""
    source_updated_at: datetime | None = None
    source_sequence: str | int | None = None
    sensitivity: str = "internal"
    privacy_profile: str = ""
    access_policy: Mapping[str, Any] = field(default_factory=dict)
    analytics: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = normalize_envelope_payload(self)
        for key, value in normalized.items():
            object.__setattr__(self, key, value)
        validate_source_object_envelope(self)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "envelope_id": self.envelope_id,
            "source_code": self.source_code,
            "source_origin": self.source_origin,
            "source_kind": self.source_kind,
            "domain": self.domain,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "operation": self.operation,
            "title": self.title,
            "text": self.text,
            "payload": dict(self.payload or {}),
            "relations": [dict(item) for item in self.relations],
            "content_hash": self.content_hash,
            "previous_content_hash": self.previous_content_hash,
            "source_updated_at": self.source_updated_at.isoformat() if self.source_updated_at else "",
            "source_sequence": self.source_sequence,
            "sensitivity": self.sensitivity,
            "privacy_profile": self.privacy_profile,
            "access_policy": dict(self.access_policy or {}),
            "analytics": dict(self.analytics or {}),
            "provenance": dict(self.provenance or {}),
        }


@runtime_checkable
class SourceAdapter(Protocol):
    source_code: str
    source_origin: str
    source_kind: str
    domain: str
    title: str

    def iter_changed_objects(self, watermark: Mapping[str, Any] | None = None) -> Iterable[Any]:
        """Return changed source objects for snapshot/reconcile sync."""

    def get_object(self, object_id: str) -> Any | None:
        """Return one source object by its stable object id, or None."""

    def render_envelope(self, source_object: Any, *, operation: str = OPERATION_UPSERT) -> SourceObjectEnvelope:
        """Render a normalized envelope for one source object."""

    def can_access(self, user: Any, envelope_or_object_id: SourceObjectEnvelope | str) -> bool:
        """Run final domain access check for adapter_check sources."""

    def extract_analytics_facts(self, envelope: SourceObjectEnvelope) -> Iterable[Mapping[str, Any]]:
        """Return normalized analytics fact candidates."""


_ADAPTERS: dict[str, SourceAdapter] = {}


def register_source_adapter(adapter: SourceAdapter, *, replace: bool = False) -> SourceAdapter:
    source_code = normalize_source_code(getattr(adapter, "source_code", ""))
    if not source_code:
        raise ValidationError("Source adapter source_code must not be empty.")
    if source_code in _ADAPTERS and not replace:
        raise ValidationError(f"Source adapter '{source_code}' is already registered.")
    _ADAPTERS[source_code] = adapter
    return adapter


def unregister_source_adapter(source_code: str) -> None:
    _ADAPTERS.pop(normalize_source_code(source_code), None)


def get_source_adapter(source_code: str) -> SourceAdapter | None:
    return _ADAPTERS.get(normalize_source_code(source_code))


def registered_source_adapters() -> dict[str, SourceAdapter]:
    return dict(_ADAPTERS)


def clear_source_adapters() -> None:
    _ADAPTERS.clear()


def resolve_privacy_profile(
    *,
    explicit_profile: str = "",
    pii_policy: str = "",
    source_origin: str = "",
    source_kind: str = "",
) -> PrivacyProfile:
    profile_id = normalize_privacy_profile_id(explicit_profile)
    if not profile_id:
        profile_id = normalize_privacy_profile_id(LEGACY_PII_POLICY_TO_PROFILE.get(str(pii_policy or "").strip(), ""))
    if not profile_id:
        origin = str(source_origin or "").strip().lower()
        kind = str(source_kind or "").strip().lower()
        profile_id = "pii_guarded" if origin == SOURCE_ORIGIN_EXTERNAL or kind in EXTERNAL_SOURCE_KINDS else "pii_off"
    try:
        return PRIVACY_PROFILES[profile_id]
    except KeyError as exc:
        raise ValidationError(f"Unsupported privacy profile: {profile_id}") from exc


def normalize_privacy_profile_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized not in PRIVACY_PROFILES:
        raise ValidationError(f"Unsupported privacy profile: {normalized}")
    return normalized


def normalize_source_code(value: str) -> str:
    return str(value or "").strip()


def stable_envelope_id(*parts: Any) -> str:
    return "envelope:" + sha256_text(":".join(str(part) for part in parts if part is not None))[:40]


def stable_content_hash(payload: Mapping[str, Any] | str) -> str:
    if isinstance(payload, str):
        return "sha256:" + sha256_text(payload)
    return "sha256:" + sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def sha256_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def default_access_policy(*, mode: str, policy_ref: str = "", scope_tokens: Iterable[str] | None = None) -> dict[str, Any]:
    return {
        "mode": mode,
        "policy_ref": policy_ref,
        "scope_tokens": sorted({str(token) for token in (scope_tokens or []) if str(token).strip()}),
    }


def default_provenance(*, adapter: str, adapter_version: str = "v1") -> dict[str, Any]:
    return {
        "adapter": adapter,
        "adapter_version": adapter_version,
        "generated_at": timezone.now().isoformat(),
    }


def normalize_envelope_payload(envelope: SourceObjectEnvelope) -> dict[str, Any]:
    source_code = normalize_source_code(envelope.source_code)
    source_origin = str(envelope.source_origin or SOURCE_ORIGIN_INTERNAL).strip().lower()
    source_kind = str(envelope.source_kind or "").strip().lower()
    operation = str(envelope.operation or OPERATION_UPSERT).strip().lower()
    source_updated_at = envelope.source_updated_at or timezone.now()
    privacy_profile = resolve_privacy_profile(
        explicit_profile=envelope.privacy_profile,
        source_origin=source_origin,
        source_kind=source_kind,
    ).profile_id
    content_hash = str(envelope.content_hash or "").strip() or stable_content_hash(
        {
            "source_code": source_code,
            "object_type": envelope.object_type,
            "object_id": envelope.object_id,
            "title": envelope.title,
            "text": envelope.text,
            "payload": envelope.payload,
            "relations": envelope.relations,
        }
    )
    envelope_id = str(envelope.envelope_id or "").strip() or stable_envelope_id(
        source_code,
        envelope.object_type,
        envelope.object_id,
        content_hash,
    )
    access_policy = dict(envelope.access_policy or {})
    if "scope_tokens" in access_policy:
        access_policy["scope_tokens"] = sorted(
            {str(token) for token in (access_policy.get("scope_tokens") or []) if str(token).strip()}
        )
    return {
        "source_code": source_code,
        "source_origin": source_origin,
        "source_kind": source_kind,
        "operation": operation,
        "source_updated_at": source_updated_at,
        "privacy_profile": privacy_profile,
        "content_hash": content_hash,
        "envelope_id": envelope_id,
        "payload": dict(envelope.payload or {}),
        "relations": tuple(dict(item) for item in (envelope.relations or ())),
        "access_policy": access_policy,
        "analytics": dict(envelope.analytics or {}),
        "provenance": dict(envelope.provenance or {}),
    }


def validate_source_object_envelope(envelope: SourceObjectEnvelope) -> None:
    if envelope.schema_version != SCHEMA_VERSION:
        raise ValidationError("Unsupported SourceObjectEnvelope schema_version.")
    required_text_fields = {
        "source_code": envelope.source_code,
        "source_origin": envelope.source_origin,
        "source_kind": envelope.source_kind,
        "domain": envelope.domain,
        "object_type": envelope.object_type,
        "object_id": envelope.object_id,
        "title": envelope.title,
        "content_hash": envelope.content_hash,
        "envelope_id": envelope.envelope_id,
    }
    for field_name, value in required_text_fields.items():
        if not str(value or "").strip():
            raise ValidationError(f"SourceObjectEnvelope.{field_name} must not be empty.")
    if envelope.operation not in {OPERATION_UPSERT, OPERATION_DELETE}:
        raise ValidationError("SourceObjectEnvelope.operation must be upsert or delete.")
    if envelope.source_origin not in {SOURCE_ORIGIN_INTERNAL, SOURCE_ORIGIN_EXTERNAL}:
        raise ValidationError("SourceObjectEnvelope.source_origin must be internal or external.")
    if envelope.operation == OPERATION_UPSERT and not str(envelope.text or "").strip():
        raise ValidationError("SourceObjectEnvelope.text must not be empty for upsert operations.")
    resolve_privacy_profile(
        explicit_profile=envelope.privacy_profile,
        source_origin=envelope.source_origin,
        source_kind=envelope.source_kind,
    )
    access_policy = dict(envelope.access_policy or {})
    mode = str(access_policy.get("mode") or "").strip()
    if mode and mode not in {
        ACCESS_MODE_SCOPE_TOKENS,
        ACCESS_MODE_ACL_INHERITED,
        ACCESS_MODE_MANUAL_MAPPING,
        ACCESS_MODE_ADAPTER_CHECK,
    }:
        raise ValidationError("SourceObjectEnvelope.access_policy.mode is unsupported.")


__all__ = [
    "ACCESS_MODE_ACL_INHERITED",
    "ACCESS_MODE_ADAPTER_CHECK",
    "ACCESS_MODE_MANUAL_MAPPING",
    "ACCESS_MODE_SCOPE_TOKENS",
    "OPERATION_DELETE",
    "OPERATION_UPSERT",
    "PRIVACY_PROFILES",
    "PrivacyProfile",
    "SCHEMA_VERSION",
    "SOURCE_ORIGIN_EXTERNAL",
    "SOURCE_ORIGIN_INTERNAL",
    "SourceAdapter",
    "SourceObjectEnvelope",
    "clear_source_adapters",
    "default_access_policy",
    "default_provenance",
    "get_source_adapter",
    "registered_source_adapters",
    "register_source_adapter",
    "resolve_privacy_profile",
    "stable_content_hash",
    "stable_envelope_id",
    "unregister_source_adapter",
    "validate_source_object_envelope",
]
