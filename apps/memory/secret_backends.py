from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.conf import settings

from .models import SecretAccessAudit, SecretHandle


@dataclass(frozen=True)
class SecretHandleRef:
    handle: str
    provider: str
    url: str


class ExternalVaultLinkBackend:
    """MVP backend: create metadata-only handles for user-managed vault values."""

    provider = SecretHandle.Provider.EXTERNAL_VAULT_LINK

    def create_secret(self, *, actor, label: str, metadata=None, scope="personal") -> SecretHandleRef:
        handle = f"secret:{uuid.uuid4()}"
        url = _build_external_vault_url(handle)
        secret = SecretHandle.objects.create(
            handle=handle,
            provider=self.provider,
            label=label[:255] or "Secret",
            owner_user=actor if scope == "personal" else None,
            scope=scope,
            url=url,
            metadata=_safe_metadata(metadata or {}),
            created_by=actor,
        )
        SecretAccessAudit.objects.create(
            actor=actor,
            secret_handle=secret,
            action=SecretAccessAudit.Action.CREATE,
            decision=SecretAccessAudit.Decision.ALLOWED,
            metadata={"provider": self.provider},
        )
        return SecretHandleRef(handle=secret.handle, provider=secret.provider, url=secret.url)

    def get_secret_url(self, *, actor, handle: str) -> str:
        secret = SecretHandle.objects.get(handle=handle)
        SecretAccessAudit.objects.create(
            actor=actor,
            secret_handle=secret,
            action=SecretAccessAudit.Action.LINK,
            decision=SecretAccessAudit.Decision.ALLOWED,
            metadata={"provider": secret.provider},
        )
        return secret.url


def get_secret_backend():
    return ExternalVaultLinkBackend()


def _build_external_vault_url(handle: str) -> str:
    base_url = str(getattr(settings, "LOCAL_BUSINESS_SECRET_VAULT_BASE_URL", "") or "").rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/#/vault?handle={handle}"


def _safe_metadata(metadata: dict) -> dict:
    blocked_keys = {"value", "secret", "password", "token", "api_key", "private_key"}
    return {str(key): value for key, value in dict(metadata or {}).items() if str(key).lower() not in blocked_keys}
