import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    NotificationBrowserClient,
    NotificationChannel,
    NotificationDeviceToken,
    NotificationPreference,
    NotificationRecipient,
    NotificationRecipientState,
)
from .services import (
    DEVICE_SCOPE_ACK,
    create_device_link_code,
    create_notification_event,
    hash_device_token,
)

User = get_user_model()


class NotificationApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="notify-user", password="pass")
        self.other = User.objects.create_user(username="notify-other", password="pass")

    def _create_event(self, recipients=None, title="Новая заявка №1"):
        return create_notification_event(
            event_type="workorders.created",
            source_app="workorders",
            source_object_type="workorder",
            source_object_id="1",
            title=title,
            body="Открыть в портале",
            target_url="/workorders/1/",
            recipients=recipients or [self.user],
        )

    def _post_json(self, url_name, payload):
        return self.client.post(
            reverse(url_name),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_feed_returns_only_current_user_notifications(self):
        own_event = self._create_event(recipients=[self.user])
        self._create_event(recipients=[self.other], title="Чужая заявка №2")
        own_recipient = NotificationRecipient.objects.get(event=own_event, user=self.user)

        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:api_feed"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["items"]], [own_recipient.pk])
        self.assertEqual(payload["unread_count"], 1)
        self.assertEqual(payload["new_count"], 1)
        own_recipient.refresh_from_db()
        self.assertIsNotNone(own_recipient.delivered_at)

    def test_feed_cursor_returns_only_newer_recipients(self):
        first_event = self._create_event(title="Первая заявка")
        second_event = self._create_event(title="Вторая заявка")
        first = NotificationRecipient.objects.get(event=first_event, user=self.user)
        second = NotificationRecipient.objects.get(event=second_event, user=self.user)

        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:api_feed"), {"cursor": first.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["items"]], [second.pk])

    def test_mark_read_is_idempotent_and_does_not_touch_foreign_recipient(self):
        own_event = self._create_event(recipients=[self.user])
        foreign_event = self._create_event(recipients=[self.other], title="Чужая заявка")
        own = NotificationRecipient.objects.get(event=own_event, user=self.user)
        foreign = NotificationRecipient.objects.get(event=foreign_event, user=self.other)

        self.client.force_login(self.user)
        response = self._post_json("notifications:api_mark_read", {"ids": [own.pk, foreign.pk]})
        second_response = self._post_json("notifications:api_mark_read", {"ids": [own.pk]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        own.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(own.state, NotificationRecipientState.READ)
        self.assertEqual(foreign.state, NotificationRecipientState.NEW)
        self.assertEqual(response.json()["updated"], 1)

    def test_browser_client_registration_hashes_fingerprint_and_updates_preference(self):
        self.client.force_login(self.user)

        response = self._post_json(
            "notifications:api_browser_client",
            {
                "fingerprint": "raw-browser-fingerprint",
                "permission": "granted",
                "enabled": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        browser_client = NotificationBrowserClient.objects.get(user=self.user)
        self.assertTrue(browser_client.enabled)
        self.assertNotEqual(browser_client.browser_fingerprint_hash, "raw-browser-fingerprint")
        preference = NotificationPreference.objects.get(
            user=self.user,
            channel=NotificationChannel.BROWSER,
            event_type="*",
        )
        self.assertTrue(preference.enabled)

    def test_unauthenticated_feed_redirects_to_login(self):
        response = self.client.get(reverse("notifications:api_feed"))

        self.assertEqual(response.status_code, 302)


class NotificationDeviceApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="device-user", password="pass")
        self.other = User.objects.create_user(username="device-other", password="pass")

    def _create_event(self, recipients=None, title="Заявка №10 назначена вам"):
        return create_notification_event(
            event_type="workorders.assigned",
            source_app="workorders",
            source_object_type="workorder",
            source_object_id="10",
            title=title,
            body="Открыть в портале",
            target_url="/workorders/10/",
            recipients=recipients or [self.user],
        )

    def _post_json(self, url_name, payload, token=None):
        headers = {}
        if token:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return self.client.post(
            reverse(url_name),
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

    def _exchange_token(self):
        _, code = create_device_link_code(self.user)
        response = self._post_json(
            "notifications:api_device_exchange_code",
            {
                "code": code,
                "device_name": "Рабочий ноутбук",
                "platform": "windows",
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["device_token"]

    def test_exchange_code_returns_token_once_and_stores_only_hash(self):
        link_code, code = create_device_link_code(self.user)

        response = self._post_json(
            "notifications:api_device_exchange_code",
            {
                "code": code,
                "device_name": "Рабочий ноутбук",
                "platform": "windows",
            },
        )
        second_response = self._post_json(
            "notifications:api_device_exchange_code",
            {
                "code": code,
                "device_name": "Повтор",
                "platform": "linux",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(second_response.status_code, 400)
        raw_token = response.json()["device_token"]
        device = NotificationDeviceToken.objects.get(user=self.user)
        self.assertNotEqual(device.token_hash, raw_token)
        link_code.refresh_from_db()
        self.assertIsNotNone(link_code.used_at)

    def test_device_feed_uses_bearer_token_and_only_current_user_queue(self):
        token = self._exchange_token()
        own_event = self._create_event(recipients=[self.user])
        self._create_event(recipients=[self.other], title="Чужая заявка")
        own_recipient = NotificationRecipient.objects.get(event=own_event, user=self.user)

        response = self.client.get(
            reverse("notifications:api_device_feed"),
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["id"] for item in payload["items"]], [own_recipient.pk])
        own_recipient.refresh_from_db()
        self.assertIsNotNone(own_recipient.delivered_at)

    def test_device_ack_does_not_touch_foreign_recipient(self):
        token = self._exchange_token()
        own_event = self._create_event(recipients=[self.user])
        foreign_event = self._create_event(recipients=[self.other], title="Чужая заявка")
        own = NotificationRecipient.objects.get(event=own_event, user=self.user)
        foreign = NotificationRecipient.objects.get(event=foreign_event, user=self.other)

        response = self._post_json(
            "notifications:api_device_ack",
            {"ids": [own.pk, foreign.pk], "action": "read"},
            token=token,
        )

        self.assertEqual(response.status_code, 200)
        own.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(own.state, NotificationRecipientState.READ)
        self.assertEqual(foreign.state, NotificationRecipientState.NEW)
        self.assertEqual(response.json()["updated"], 1)

    def test_device_revoke_invalidates_token(self):
        token = self._exchange_token()

        response = self._post_json("notifications:api_device_revoke", {}, token=token)
        feed_response = self.client.get(
            reverse("notifications:api_device_feed"),
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(feed_response.status_code, 401)
        self.assertIsNotNone(NotificationDeviceToken.objects.get(user=self.user).revoked_at)

    def test_device_feed_requires_read_scope(self):
        raw_token = "lbsn_dt_scope_test"
        NotificationDeviceToken.objects.create(
            user=self.user,
            device_name="Без чтения",
            platform="linux",
            token_hash=hash_device_token(raw_token),
            scopes=[DEVICE_SCOPE_ACK],
        )

        response = self.client.get(
            reverse("notifications:api_device_feed"),
            HTTP_AUTHORIZATION=f"Bearer {raw_token}",
        )

        self.assertEqual(response.status_code, 403)
