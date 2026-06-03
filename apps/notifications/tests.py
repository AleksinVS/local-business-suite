import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    NotificationBrowserClient,
    NotificationChannel,
    NotificationPreference,
    NotificationRecipient,
    NotificationRecipientState,
)
from .services import create_notification_event

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
