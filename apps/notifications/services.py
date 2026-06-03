import hashlib
from typing import Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import (
    BrowserNotificationPermission,
    NotificationBrowserClient,
    NotificationChannel,
    NotificationEvent,
    NotificationPreference,
    NotificationRecipient,
    NotificationRecipientState,
    NotificationSeverity,
)
from .selectors import new_count_for_user, unread_count_for_user

User = get_user_model()

SEVERITY_ORDER = {
    NotificationSeverity.INFO: 10,
    NotificationSeverity.WARNING: 20,
    NotificationSeverity.CRITICAL: 30,
}


def safe_portal_url(target_url: str) -> str:
    url = (target_url or "").strip()
    if not url.startswith("/") or url.startswith("//"):
        return "/"
    return url


def safe_text(value: str, *, max_length: int) -> str:
    cleaned = " ".join(str(value or "").split())
    return cleaned[:max_length]


def _active_unique_users(recipients: Iterable) -> list:
    users_by_id = {}
    ids = set()
    for recipient in recipients or []:
        if recipient is None:
            continue
        if hasattr(recipient, "pk"):
            if getattr(recipient, "is_active", True):
                users_by_id[recipient.pk] = recipient
            continue
        try:
            ids.add(int(recipient))
        except (TypeError, ValueError):
            continue
    if ids:
        for user in User.objects.filter(pk__in=ids, is_active=True):
            users_by_id[user.pk] = user
    return list(users_by_id.values())


@transaction.atomic
def create_notification_event(
    *,
    event_type: str,
    source_app: str,
    source_object_type: str,
    source_object_id,
    title: str,
    body: str,
    target_url: str,
    recipients: Iterable,
    severity: str = NotificationSeverity.INFO,
    metadata: dict | None = None,
) -> NotificationEvent | None:
    users = _active_unique_users(recipients)
    if not users:
        return None

    normalized_severity = severity if severity in NotificationSeverity.values else NotificationSeverity.INFO
    event = NotificationEvent.objects.create(
        event_type=safe_text(event_type, max_length=120),
        source_app=safe_text(source_app, max_length=64),
        source_object_type=safe_text(source_object_type, max_length=80),
        source_object_id=safe_text(str(source_object_id), max_length=120),
        title=safe_text(title, max_length=160),
        body=safe_text(body, max_length=240),
        target_url=safe_portal_url(target_url),
        severity=normalized_severity,
        metadata=metadata or {},
    )
    NotificationRecipient.objects.bulk_create(
        [NotificationRecipient(event=event, user=user) for user in users],
        ignore_conflicts=True,
    )
    return event


def serialize_recipient(recipient: NotificationRecipient) -> dict:
    event = recipient.event
    return {
        "id": recipient.pk,
        "cursor": recipient.cursor,
        "state": recipient.state,
        "event_id": str(event.event_id),
        "event_type": event.event_type,
        "source_app": event.source_app,
        "source_object_type": event.source_object_type,
        "source_object_id": event.source_object_id,
        "title": event.title,
        "body": event.body,
        "target_url": event.target_url,
        "severity": event.severity,
        "created_at": event.created_at.isoformat(),
        "delivered_at": recipient.delivered_at.isoformat() if recipient.delivered_at else None,
    }


def mark_recipients_delivered(user, recipient_ids):
    now = timezone.now()
    return NotificationRecipient.objects.filter(
        user=user,
        pk__in=recipient_ids,
        delivered_at__isnull=True,
    ).update(delivered_at=now)


def mark_seen(user, recipient_ids):
    now = timezone.now()
    updated = NotificationRecipient.objects.filter(
        user=user,
        pk__in=recipient_ids,
        state=NotificationRecipientState.NEW,
    ).update(state=NotificationRecipientState.SEEN, seen_at=now)
    return {
        "updated": updated,
        "unread_count": unread_count_for_user(user),
        "new_count": new_count_for_user(user),
    }


def mark_read(user, recipient_ids):
    now = timezone.now()
    updated = NotificationRecipient.objects.filter(
        user=user,
        pk__in=recipient_ids,
    ).exclude(
        state=NotificationRecipientState.DISMISSED
    ).update(
        state=NotificationRecipientState.READ,
        seen_at=now,
        read_at=now,
    )
    return {
        "updated": updated,
        "unread_count": unread_count_for_user(user),
        "new_count": new_count_for_user(user),
    }


def dismiss(user, recipient_ids):
    now = timezone.now()
    updated = NotificationRecipient.objects.filter(
        user=user,
        pk__in=recipient_ids,
    ).update(
        state=NotificationRecipientState.DISMISSED,
        seen_at=now,
        read_at=now,
        dismissed_at=now,
    )
    return {
        "updated": updated,
        "unread_count": unread_count_for_user(user),
        "new_count": new_count_for_user(user),
    }


def preference_enabled(user, *, channel: str, event_type: str = "*") -> bool:
    preference = NotificationPreference.objects.filter(
        user=user,
        channel=channel,
        event_type=event_type,
    ).first()
    if preference is not None:
        return preference.enabled
    if event_type != "*":
        return preference_enabled(user, channel=channel, event_type="*")
    return channel == NotificationChannel.IN_APP


def update_browser_preference(user, *, enabled: bool) -> NotificationPreference:
    preference, _ = NotificationPreference.objects.update_or_create(
        user=user,
        channel=NotificationChannel.BROWSER,
        event_type="*",
        defaults={
            "enabled": bool(enabled),
            "min_severity": NotificationSeverity.INFO,
        },
    )
    return preference


def serialize_preferences(user) -> dict:
    browser_enabled = preference_enabled(user, channel=NotificationChannel.BROWSER)
    return {
        "browser": {
            "enabled": browser_enabled,
            "event_type": "*",
            "min_severity": NotificationSeverity.INFO,
        }
    }


def _hash_browser_fingerprint(fingerprint: str) -> str:
    base = f"{settings.SECRET_KEY}:{fingerprint or ''}".encode("utf-8")
    return hashlib.sha256(base).hexdigest()


def _user_agent_family(user_agent: str) -> str:
    value = (user_agent or "").strip()
    if not value:
        return ""
    lowered = value.lower()
    if "edg/" in lowered:
        return "Edge"
    if "chrome/" in lowered and "chromium" not in lowered:
        return "Chrome"
    if "firefox/" in lowered:
        return "Firefox"
    if "safari/" in lowered:
        return "Safari"
    return value[:120]


def register_browser_client(
    *,
    user,
    fingerprint: str,
    permission: str,
    enabled: bool,
    user_agent: str,
) -> NotificationBrowserClient:
    normalized_permission = (
        permission
        if permission in BrowserNotificationPermission.values
        else BrowserNotificationPermission.DEFAULT
    )
    browser_client, _ = NotificationBrowserClient.objects.update_or_create(
        user=user,
        browser_fingerprint_hash=_hash_browser_fingerprint(fingerprint),
        defaults={
            "user_agent_family": _user_agent_family(user_agent),
            "notification_permission": normalized_permission,
            "enabled": bool(enabled) and normalized_permission == BrowserNotificationPermission.GRANTED,
            "last_seen_at": timezone.now(),
        },
    )
    update_browser_preference(
        user,
        enabled=bool(enabled) and normalized_permission == BrowserNotificationPermission.GRANTED,
    )
    return browser_client
