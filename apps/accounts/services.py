from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ExternalIdentity


SAFE_AD_ATTRIBUTE_KEYS = {
    "displayName",
    "givenName",
    "mail",
    "memberOf",
    "objectSid",
    "sAMAccountName",
    "sn",
    "userPrincipalName",
}


def create_local_user(*, actor, cleaned_data):
    _require_superuser(actor)
    User = get_user_model()
    groups = cleaned_data.pop("groups", [])
    password = cleaned_data.pop("password", "")
    user = User(**cleaned_data)
    if password:
        user.set_password(password)
    else:
        user.set_unusable_password()
    with transaction.atomic():
        user.save()
        if groups:
            user.groups.set(groups)
    return user


def update_local_user(*, actor, user, cleaned_data):
    _require_superuser(actor)
    groups = cleaned_data.pop("groups", None)
    password = cleaned_data.pop("password", "")
    for field, value in cleaned_data.items():
        setattr(user, field, value)
    if password:
        user.set_password(password)
    with transaction.atomic():
        user.save()
        if groups is not None:
            user.groups.set(groups)
    return user


def disable_local_user(*, actor, user):
    _require_superuser(actor)
    if user.pk == getattr(actor, "pk", None):
        raise ValidationError("You cannot disable your own account.")
    user.is_active = False
    user.save(update_fields=["is_active"])
    return user


def link_ad_identity(*, actor, user, cleaned_data):
    _require_superuser(actor)
    provider = cleaned_data.get("provider") or ExternalIdentity.Provider.ACTIVE_DIRECTORY
    subject_id = cleaned_data.get("subject_id", "")
    username = cleaned_data.get("username", "")
    domain = cleaned_data.get("domain", "")
    if not (subject_id or username or cleaned_data.get("upn")):
        raise ValidationError("AD link requires SID, username or UPN.")
    identity, _created = ExternalIdentity.objects.update_or_create(
        user=user,
        provider=provider,
        defaults={
            "subject_id": subject_id,
            "username": username,
            "upn": cleaned_data.get("upn", ""),
            "distinguished_name": cleaned_data.get("distinguished_name", ""),
            "domain": domain,
            "sync_status": cleaned_data.get("sync_status") or ExternalIdentity.SyncStatus.MANUAL,
            "last_synced_at": timezone.now(),
            "last_error": "",
        },
    )
    return identity


def upsert_ad_identity_from_attributes(*, user, attributes, domain=""):
    safe_attributes = {
        key: value for key, value in dict(attributes or {}).items() if key in SAFE_AD_ATTRIBUTE_KEYS
    }
    return ExternalIdentity.objects.update_or_create(
        user=user,
        provider=ExternalIdentity.Provider.ACTIVE_DIRECTORY,
        defaults={
            "subject_id": str(safe_attributes.get("objectSid", "")),
            "username": str(safe_attributes.get("sAMAccountName", "")),
            "upn": str(safe_attributes.get("userPrincipalName", "")),
            "domain": domain,
            "attributes": safe_attributes,
            "sync_status": ExternalIdentity.SyncStatus.VERIFIED,
            "last_synced_at": timezone.now(),
            "last_error": "",
        },
    )[0]


def scope_tokens_for_principal(*, sid="", username="", domain=""):
    tokens = set()
    if sid:
        identity = ExternalIdentity.objects.filter(
            provider=ExternalIdentity.Provider.ACTIVE_DIRECTORY,
            subject_id=sid,
        ).select_related("user").first()
        if identity and identity.user.is_active:
            tokens.add(f"user:{identity.user_id}")
    if username:
        qs = ExternalIdentity.objects.filter(
            provider=ExternalIdentity.Provider.ACTIVE_DIRECTORY,
            username__iexact=username,
        )
        if domain:
            qs = qs.filter(domain__iexact=domain)
        identity = qs.select_related("user").first()
        if identity and identity.user.is_active:
            tokens.add(f"user:{identity.user_id}")
    return tokens


def scope_tokens_for_group_names(group_names):
    tokens = set()
    existing = set(Group.objects.filter(name__in=list(group_names)).values_list("name", flat=True))
    tokens.update(f"role:{name}" for name in existing)
    return tokens


def _require_superuser(actor):
    if not getattr(actor, "is_superuser", False):
        raise PermissionDenied("Superuser permission is required.")
