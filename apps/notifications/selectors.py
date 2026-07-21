from django.db.models import QuerySet

from .models import NotificationRecipient, NotificationRecipientState


def notification_recipients_for_user(user) -> QuerySet:
    if not getattr(user, "is_authenticated", False):
        return NotificationRecipient.objects.none()
    return NotificationRecipient.objects.select_related("event", "user").filter(user=user)


def feed_for_user(user, *, cursor=0, limit=30) -> QuerySet:
    queryset = notification_recipients_for_user(user).exclude(
        state=NotificationRecipientState.DISMISSED
    )
    if cursor:
        return queryset.filter(pk__gt=cursor).order_by("id")[:limit]
    return queryset.order_by("-id")[:limit]


def unread_count_for_user(user) -> int:
    return notification_recipients_for_user(user).filter(
        state__in=[NotificationRecipientState.NEW, NotificationRecipientState.SEEN]
    ).count()


def new_count_for_user(user) -> int:
    return notification_recipients_for_user(user).filter(
        state=NotificationRecipientState.NEW
    ).count()
