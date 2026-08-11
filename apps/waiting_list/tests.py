from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.workorders.policies import ROLE_MANAGER

User = get_user_model()

from .models import SERVICE_CHOICES, WaitingListAuditLog, WaitingListEntry, WaitingListStatus
from .policies import (
    ROLE_DOCTOR,
    can_create_waiting_list,
    can_edit_waiting_list_entry,
    can_transition_waiting_list_entry,
    can_view_waiting_list,
)


def grant_doctor_role(*users):
    """Выдать роль «Врач» (доступ к листу ожидания по ADR-0034)."""
    doctor_group, _ = Group.objects.get_or_create(name=ROLE_DOCTOR)
    for user in users:
        user.groups.add(doctor_group)
from .right_panel import WaitingListRightPanelProvider
from .services import (
    WaitingListValidationError,
    create_entry,
    transition_entry,
    update_entry,
)


@pytest.mark.integration
class WaitingListModelTests(TestCase):
    """Tests for WaitingListEntry and WaitingListAuditLog models."""

    def test_entry_uses_int_pk(self):
        """Entry must use int PK, not UUID."""
        entry = WaitingListEntry.objects.create(
            patient_name="Иванов Иван Иванович",
            patient_dob=date(1985, 4, 15),
            patient_phone="+7 (903) 123-45-67",
            service_id="s1",
        )
        self.assertIsInstance(entry.pk, int)
        self.assertIsNotNone(entry.external_id)

    def test_entry_str_representation(self):
        """Entry string representation includes name and service."""
        entry = WaitingListEntry.objects.create(
            patient_name="Петрова Анна Сергеевна",
            patient_dob=date(1990, 8, 22),
            patient_phone="+7 (916) 987-65-43",
            service_id="s2",
        )
        self.assertIn("Петрова Анна Сергеевна", str(entry))
        self.assertIn("МРТ позвоночника", str(entry))

    def test_entry_default_status_is_waiting(self):
        """New entries default to WAITING status."""
        entry = WaitingListEntry.objects.create(
            patient_name="Тестов Тест Тестович",
            patient_dob=date(1990, 1, 1),
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )
        self.assertEqual(entry.status, WaitingListStatus.WAITING)

    def test_entry_audit_log_created_on_creation(self):
        """Creating an entry via service creates an audit log."""
        user = User.objects.create_user(username="testuser", password="pass")
        entry = create_entry(
            author=user,
            patient_name="Тестов Тест Тестович",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )
        self.assertEqual(entry.audit_logs.count(), 1)
        self.assertEqual(entry.audit_logs.first().actor, user)

    def test_entry_cito_priority(self):
        """CITO priority flag works correctly."""
        entry = WaitingListEntry.objects.create(
            patient_name="Срочный Пациент",
            patient_dob=date(1980, 5, 5),
            patient_phone="+7 (999) 999-99-99",
            service_id="s1",
            priority_cito=True,
        )
        self.assertTrue(entry.priority_cito)


@pytest.mark.integration
class WaitingListValidationTests(TestCase):
    """Tests for server-side validation in services."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="valuser", password="pass")

    def test_create_entry_requires_name_min_length(self):
        with self.assertRaises(WaitingListValidationError):
            create_entry(
                author=self.user,
                patient_name="A",
                patient_dob="01.01.1990",
                patient_phone="+7 (900) 111-22-33",
                service_id="s1",
            )

    def test_create_entry_requires_valid_dob_format(self):
        with self.assertRaises(WaitingListValidationError):
            create_entry(
                author=self.user,
                patient_name="Valid Name",
                patient_dob="not-a-date",
                patient_phone="+7 (900) 111-22-33",
                service_id="s1",
            )

    def test_create_entry_requires_valid_phone(self):
        with self.assertRaises(WaitingListValidationError):
            create_entry(
                author=self.user,
                patient_name="Valid Name",
                patient_dob="01.01.1990",
                patient_phone="12345",
                service_id="s1",
            )

    def test_update_entry_validates_dob(self):
        entry = create_entry(
            author=self.user,
            patient_name="Original",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )
        with self.assertRaises(WaitingListValidationError):
            update_entry(
                entry=entry,
                user=self.user,
                patient_dob="invalid",
            )

    def test_update_entry_logs_only_actual_fields_and_can_clear_dates(self):
        entry = create_entry(
            author=self.user,
            patient_name="Исходный Пациент",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
            date_tag=date(2026, 9, 1),
            comment="Старый комментарий",
        )

        updated = update_entry(
            entry=entry,
            user=self.user,
            patient_name="Исходный Пациент",
            date_tag=None,
            comment="Новый комментарий",
        )

        self.assertIsNone(updated.date_tag)
        self.assertEqual(updated.comment, "Новый комментарий")
        self.assertEqual(updated.audit_logs.count(), 2)
        action = updated.audit_logs.first().action
        self.assertEqual(action, "Изменены поля: целевая дата, комментарий")
        self.assertNotIn("Старый комментарий", action)
        self.assertNotIn("Новый комментарий", action)

    def test_update_entry_without_changes_does_not_create_false_audit(self):
        entry = create_entry(
            author=self.user,
            patient_name="Неизменный Пациент",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )

        update_entry(
            entry=entry,
            user=self.user,
            patient_name=entry.patient_name,
            patient_dob=entry.patient_dob,
            patient_phone=entry.patient_phone,
            service_id=entry.service_id,
            date_tag=entry.date_tag,
            date_end=entry.date_end,
            priority_cito=entry.priority_cito,
            comment=entry.comment,
        )

        self.assertEqual(entry.audit_logs.count(), 1)

    def test_update_entry_rolls_back_data_when_audit_write_fails(self):
        entry = create_entry(
            author=self.user,
            patient_name="Атомарный Пациент",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )

        with patch(
            "apps.waiting_list.services._create_audit_log",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                update_entry(
                    entry=entry,
                    user=self.user,
                    patient_phone="+7 (900) 999-88-77",
                )

        entry.refresh_from_db()
        self.assertEqual(entry.patient_phone, "+7 (900) 111-22-33")
        self.assertEqual(entry.audit_logs.count(), 1)


@pytest.mark.integration
class WaitingListPolicyTests(TestCase):
    """Tests for waiting list policy layer."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="policyuser", password="pass")
        cls.manager = User.objects.create_user(username="manager", password="pass")
        cls.outsider = User.objects.create_user(username="outsider", password="pass")
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        cls.manager.groups.add(manager_group)
        grant_doctor_role(cls.user)

        cls.entry = create_entry(
            author=cls.user,
            patient_name="Пациент",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )

    def test_doctor_can_view(self):
        self.assertTrue(can_view_waiting_list(self.user))
        self.assertTrue(can_create_waiting_list(self.user))

    def test_non_doctor_cannot_view(self):
        # ADR-0034: лист ожидания доступен только ролям с правом
        # view_waiting_list (по умолчанию — «Врач»); менеджер и просто
        # авторизованный пользователь доступа не имеют.
        self.assertFalse(can_view_waiting_list(self.outsider))
        self.assertFalse(can_view_waiting_list(self.manager))
        self.assertFalse(can_create_waiting_list(self.outsider))

    def test_superuser_can_view(self):
        superuser = User.objects.create_superuser(username="wl-root", password="pass")
        self.assertTrue(can_view_waiting_list(superuser))

    def test_author_can_edit(self):
        self.assertTrue(can_edit_waiting_list_entry(self.user, self.entry))

    def test_manager_can_edit_any_entry(self):
        self.assertTrue(can_edit_waiting_list_entry(self.manager, self.entry))

    def test_outsider_cannot_edit(self):
        self.assertFalse(can_edit_waiting_list_entry(self.outsider, self.entry))

    def test_author_can_transition(self):
        self.assertTrue(can_transition_waiting_list_entry(self.user, self.entry))

    def test_manager_can_transition(self):
        self.assertTrue(can_transition_waiting_list_entry(self.manager, self.entry))

    def test_outsider_cannot_transition(self):
        self.assertFalse(can_transition_waiting_list_entry(self.outsider, self.entry))


@pytest.mark.integration
class WaitingListRouteTests(TestCase):
    """Tests for waiting list routes and HTMX behavior."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="routeuser", password="pass")
        grant_doctor_role(cls.user)
        cls.entry = create_entry(
            author=cls.user,
            patient_name="Маршрутный Пациент",
            patient_dob="15.04.1985",
            patient_phone="+7 (903) 123-45-67",
            service_id="s1",
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("waiting_list:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_returns_200_for_doctor(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("waiting_list:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "page-container--flush-toolbar")

    def test_dashboard_forbidden_without_doctor_role(self):
        non_doctor = User.objects.create_user(username="nondoctor", password="pass")
        self.client.force_login(non_doctor)
        response = self.client.get(reverse("waiting_list:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_create_entry_form_renders(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("waiting_list:create"))
        self.assertEqual(response.status_code, 200)

    def test_create_entry_post_creates_record(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("waiting_list:create"),
            {
                "patient_name": "Новый Пациент",
                "patient_dob": "20.05.1980",
                "patient_phone": "+7 (905) 123-45-67",
                "service_id": "s2",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            WaitingListEntry.objects.filter(patient_name="Новый Пациент").exists()
        )

    def test_detail_view_renders(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("waiting_list:detail", kwargs={"pk": self.entry.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.entry.patient_name)

    def test_detail_htmx_partial_publishes_ai_context(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("waiting_list:detail", kwargs={"pk": self.entry.pk}),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-ai-context="')
        self.assertContains(response, "waiting_list_entry")
        self.assertContains(response, 'data-waiting-list-inline-form')
        self.assertContains(response, 'value="15.04.1985"')
        self.assertContains(response, 'class="waiting-list-edit-card"', count=4)
        self.assertContains(response, "Пациент")
        self.assertContains(response, "Контакты")
        self.assertContains(response, "Услуга и сроки")
        self.assertContains(response, "Комментарий и приоритет")
        self.assertNotContains(response, ">Редактировать<")

    def test_inline_update_returns_same_panel_and_audits_changed_fields(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("waiting_list:update", kwargs={"pk": self.entry.pk}),
            {
                "patient_name": self.entry.patient_name,
                "patient_dob": "15.04.1985",
                "patient_phone": "+7 (903) 765-43-21",
                "service_id": self.entry.service_id,
                "date_tag": "",
                "date_end": "",
                "priority_cito": "on",
                "comment": "Уточнение из окна просмотра",
            },
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="waiting-list-inline-form",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["HX-Trigger"], "waitingListEntryUpdated")
        self.assertContains(response, 'data-waiting-list-inline-form')
        self.assertContains(response, "Изменены поля: телефон, приоритет CITO, комментарий")
        self.assertNotContains(response, ">Редактировать<")
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.patient_phone, "+7 (903) 765-43-21")
        self.assertTrue(self.entry.priority_cito)
        self.assertEqual(self.entry.audit_logs.count(), 2)

    def test_inline_update_validation_error_stays_in_detail_panel(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("waiting_list:update", kwargs={"pk": self.entry.pk}),
            {
                "patient_name": self.entry.patient_name,
                "patient_dob": "15.04.1985",
                "patient_phone": "123",
                "service_id": self.entry.service_id,
                "date_tag": "",
                "date_end": "",
                "comment": "",
            },
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="waiting-list-inline-form",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-waiting-list-detail')
        self.assertContains(response, 'data-waiting-list-inline-form')
        self.assertContains(response, "Неверный формат телефона")
        self.assertContains(response, 'waiting-list-edit-card is-editing')
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.patient_phone, "+7 (903) 123-45-67")
        self.assertEqual(self.entry.audit_logs.count(), 1)

    def test_view_only_user_sees_read_only_panel_and_cannot_post_update(self):
        viewer = User.objects.create_user(username="waiting-viewer", password="pass")
        grant_doctor_role(viewer)
        self.client.force_login(viewer)

        detail_response = self.client.get(
            reverse("waiting_list:detail", kwargs={"pk": self.entry.pk}),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertNotContains(detail_response, 'data-waiting-list-inline-form')
        self.assertContains(detail_response, self.entry.patient_phone)

        update_response = self.client.post(
            reverse("waiting_list:update", kwargs={"pk": self.entry.pk}),
            {
                "patient_name": "Попытка изменения",
                "patient_dob": "15.04.1985",
                "patient_phone": "+7 (903) 999-99-99",
                "service_id": "s1",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(update_response.status_code, 403)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.patient_name, "Маршрутный Пациент")
        self.assertEqual(self.entry.audit_logs.count(), 1)

    def test_right_panel_provider_returns_descriptor_for_visible_entry(self):
        provider = WaitingListRightPanelProvider()

        descriptor = provider.build_panel(self.user, str(self.entry.pk))

        self.assertTrue(provider.can_open(self.user, str(self.entry.pk)))
        self.assertEqual(descriptor.source_code, "waiting_list")
        self.assertEqual(descriptor.object_type, "waiting_list_entry")
        self.assertEqual(descriptor.object_id, str(self.entry.pk))
        self.assertEqual(descriptor.drawer_size, "waiting_list")
        self.assertIn(reverse("waiting_list:detail", kwargs={"pk": self.entry.pk}), descriptor.htmx_url)

    def test_transition_changes_status(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("waiting_list:transition", kwargs={"pk": self.entry.pk}),
            {"status": WaitingListStatus.SCHEDULED},
        )
        self.assertEqual(response.status_code, 302)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, WaitingListStatus.SCHEDULED)

    def test_unauthorized_user_cannot_transition(self):
        outsider = User.objects.create_user(username="unauthorized", password="pass")
        self.client.force_login(outsider)
        response = self.client.post(
            reverse("waiting_list:transition", kwargs={"pk": self.entry.pk}),
            {"status": WaitingListStatus.SCHEDULED},
        )
        self.assertEqual(response.status_code, 403)

    def test_audit_log_created_on_transition(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("waiting_list:transition", kwargs={"pk": self.entry.pk}),
            {"status": WaitingListStatus.SCHEDULED},
        )
        self.assertEqual(self.entry.audit_logs.count(), 2)
