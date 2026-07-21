import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from django.utils.decorators import method_decorator

from .models import NotificationDeviceToken
from .selectors import feed_for_user, new_count_for_user, unread_count_for_user
from .services import (
    DEVICE_SCOPE_ACK,
    DEVICE_SCOPE_READ,
    authenticate_device_token,
    create_device_link_code,
    device_has_scope,
    dismiss,
    exchange_device_link_code,
    mark_read,
    mark_recipients_delivered,
    mark_seen,
    register_browser_client,
    serialize_preferences,
    serialize_recipient,
    serialize_device,
    touch_device,
    update_browser_preference,
    revoke_device,
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


class NotificationDevicesView(LoginRequiredMixin, TemplateView):
    template_name = "notifications/devices.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["devices"] = NotificationDeviceToken.objects.filter(
            user=self.request.user
        ).order_by("-created_at", "-id")
        return context


class NotificationDeviceLinkCodeCreateView(LoginRequiredMixin, View):
    def post(self, request):
        link_code, display_code = create_device_link_code(request.user)
        view = NotificationDevicesView()
        view.request = request
        context = view.get_context_data()
        context["new_link_code"] = display_code
        context["new_link_code_expires_at"] = link_code.expires_at
        return view.render_to_response(context)


class NotificationDeviceRevokeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        device = get_object_or_404(NotificationDeviceToken, pk=pk, user=request.user)
        revoke_device(device)
        return redirect("notifications:devices")


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


def _device_from_request(request):
    return authenticate_device_token(request.META.get("HTTP_AUTHORIZATION", ""))


def _device_unauthorized():
    return JsonResponse({"error": "invalid_device_token"}, status=401)


def _device_forbidden():
    return JsonResponse({"error": "insufficient_scope"}, status=403)


@method_decorator(csrf_exempt, name="dispatch")
class NotificationDeviceExchangeCodeApiView(View):
    def post(self, request):
        payload = _parse_json_body(request)
        result = exchange_device_link_code(
            code=str(payload.get("code") or ""),
            device_name=str(payload.get("device_name") or ""),
            platform=str(payload.get("platform") or ""),
        )
        if result is None:
            return JsonResponse({"error": "invalid_or_expired_code"}, status=400)
        return JsonResponse(
            {
                "device": serialize_device(result.device),
                "device_token": result.raw_token,
                "user": {
                    "id": result.device.user_id,
                    "display_name": result.device.user.get_full_name() or result.device.user.username,
                },
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class NotificationDeviceFeedApiView(View):
    def get(self, request):
        device = _device_from_request(request)
        if device is None:
            return _device_unauthorized()
        if not device_has_scope(device, DEVICE_SCOPE_READ):
            return _device_forbidden()
        touch_device(device)
        try:
            cursor = int(request.GET.get("cursor") or 0)
        except ValueError:
            cursor = 0
        recipients = list(feed_for_user(device.user, cursor=max(cursor, 0)))
        delivered_at = timezone.now()
        mark_recipients_delivered(device.user, [recipient.pk for recipient in recipients])
        for recipient in recipients:
            if not recipient.delivered_at:
                recipient.delivered_at = delivered_at
        max_cursor = max([cursor, *[recipient.pk for recipient in recipients]], default=cursor)
        return JsonResponse(
            {
                "items": [serialize_recipient(recipient) for recipient in recipients],
                "cursor": max_cursor,
                "unread_count": unread_count_for_user(device.user),
                "new_count": new_count_for_user(device.user),
                "device": serialize_device(device),
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class NotificationDeviceAckApiView(View):
    def post(self, request):
        device = _device_from_request(request)
        if device is None:
            return _device_unauthorized()
        if not device_has_scope(device, DEVICE_SCOPE_ACK):
            return _device_forbidden()
        touch_device(device)
        payload = _parse_json_body(request)
        ids = _ids_from_payload(payload)
        action = str(payload.get("action") or "read")
        if action == "seen":
            result = mark_seen(device.user, ids)
        elif action == "dismiss":
            result = dismiss(device.user, ids)
        else:
            result = mark_read(device.user, ids)
        return JsonResponse(result)


@method_decorator(csrf_exempt, name="dispatch")
class NotificationDeviceRevokeApiView(View):
    def post(self, request):
        device = _device_from_request(request)
        if device is None:
            return _device_unauthorized()
        revoke_device(device)
        return JsonResponse({"revoked": True})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def service_worker(request):
    path = finders.find("service-worker.js")
    if not path:
        raise Http404("Service worker not found")
    return FileResponse(open(path, "rb"), content_type="application/javascript")
