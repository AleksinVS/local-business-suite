import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404, JsonResponse
from django.utils import timezone
from django.views import View
from django.views.decorators.cache import cache_control
from django.views.generic import TemplateView

from .selectors import feed_for_user, new_count_for_user, unread_count_for_user
from .services import (
    dismiss,
    mark_read,
    mark_recipients_delivered,
    mark_seen,
    register_browser_client,
    serialize_preferences,
    serialize_recipient,
    update_browser_preference,
)


def _parse_json_body(request) -> dict:
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _ids_from_payload(payload) -> list[int]:
    values = payload.get("ids")
    if values is None:
        values = [payload.get("id")]
    ids = []
    for value in values or []:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            ids.append(parsed)
    return ids


class NotificationCenterView(LoginRequiredMixin, TemplateView):
    template_name = "notifications/center.html"


class NotificationFeedApiView(LoginRequiredMixin, View):
    def get(self, request):
        try:
            cursor = int(request.GET.get("cursor") or 0)
        except ValueError:
            cursor = 0
        recipients = list(feed_for_user(request.user, cursor=max(cursor, 0)))
        delivered_at = timezone.now()
        mark_recipients_delivered(request.user, [recipient.pk for recipient in recipients])
        for recipient in recipients:
            if not recipient.delivered_at:
                recipient.delivered_at = delivered_at
        max_cursor = max([cursor, *[recipient.pk for recipient in recipients]], default=cursor)
        return JsonResponse(
            {
                "items": [serialize_recipient(recipient) for recipient in recipients],
                "cursor": max_cursor,
                "unread_count": unread_count_for_user(request.user),
                "new_count": new_count_for_user(request.user),
                "preferences": serialize_preferences(request.user),
            }
        )


class NotificationMarkSeenApiView(LoginRequiredMixin, View):
    def post(self, request):
        result = mark_seen(request.user, _ids_from_payload(_parse_json_body(request)))
        return JsonResponse(result)


class NotificationMarkReadApiView(LoginRequiredMixin, View):
    def post(self, request):
        result = mark_read(request.user, _ids_from_payload(_parse_json_body(request)))
        return JsonResponse(result)


class NotificationDismissApiView(LoginRequiredMixin, View):
    def post(self, request):
        result = dismiss(request.user, _ids_from_payload(_parse_json_body(request)))
        return JsonResponse(result)


class NotificationBrowserClientApiView(LoginRequiredMixin, View):
    def post(self, request):
        payload = _parse_json_body(request)
        browser_client = register_browser_client(
            user=request.user,
            fingerprint=str(payload.get("fingerprint") or ""),
            permission=str(payload.get("permission") or "default"),
            enabled=bool(payload.get("enabled")),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return JsonResponse(
            {
                "id": browser_client.pk,
                "permission": browser_client.notification_permission,
                "enabled": browser_client.enabled,
            }
        )


class NotificationPreferencesApiView(LoginRequiredMixin, View):
    def get(self, request):
        return JsonResponse(serialize_preferences(request.user))

    def post(self, request):
        payload = _parse_json_body(request)
        browser = payload.get("browser") if isinstance(payload.get("browser"), dict) else {}
        preference = update_browser_preference(
            request.user,
            enabled=bool(browser.get("enabled")),
        )
        return JsonResponse(
            {
                "browser": {
                    "enabled": preference.enabled,
                    "event_type": preference.event_type,
                    "min_severity": preference.min_severity,
                }
            }
        )


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def service_worker(request):
    path = finders.find("service-worker.js")
    if not path:
        raise Http404("Service worker not found")
    return FileResponse(open(path, "rb"), content_type="application/javascript")
