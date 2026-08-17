"""Регрессии недоступности чужих записей листа ожидания в AI-контуре."""

import pytest

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.waiting_list.services import create_entry

from ..page_context import resolve_page_context
from ..services import get_waiting_list_entry_for_actor


@pytest.mark.integration
class WaitingListAIAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = cls._user_with_group("ai-waiting-owner", "doctor")
        cls.foreign = cls._user_with_group("ai-waiting-foreign", "customer")
        cls.entry = create_entry(
            author=cls.owner,
            patient_name="AI Чужая запись",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 555-55-55",
            service_id="s1",
        )

    @staticmethod
    def _user_with_group(username, group_name):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(username=username, password="pass")
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
        return user

    def test_ai_get_service_denies_foreign_entry(self):
        with self.assertRaises(PermissionDenied):
            get_waiting_list_entry_for_actor(actor=self.foreign, entry_id=self.entry.pk)

    def test_ai_page_context_denies_foreign_entry(self):
        with self.assertRaises(PermissionDenied):
            resolve_page_context(
                self.foreign,
                {
                    "schema_version": "1",
                    "window_id": "ai-foreign-waiting-entry",
                    "page": {"module": "waiting_list", "view": "detail"},
                    "selection": {
                        "object_type": "waiting_list_entry",
                        "object_id": str(self.entry.pk),
                        "source_code": "waiting_list",
                    },
                },
            )

    def test_ai_get_service_reloads_inactive_actor(self):
        from django.contrib.auth import get_user_model

        stale_actor = self._user_with_group("ai-waiting-stale", "doctor")
        get_user_model().objects.filter(pk=stale_actor.pk).update(is_active=False)

        with self.assertRaises(PermissionDenied):
            get_waiting_list_entry_for_actor(
                actor=stale_actor,
                entry_id=self.entry.pk,
            )
