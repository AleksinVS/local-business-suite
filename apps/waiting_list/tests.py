from datetime import date

from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.workorders.policies import ROLE_MANAGER

User = get_user_model()

from .models import SERVICE_CHOICES, WaitingListAuditLog, WaitingListEntry, WaitingListStatus
from .policies import (
    can_create_waiting_list,
    can_edit_waiting_list_entry,
    can_transition_waiting_list_entry,
    can_view_waiting_list,
)
from .right_panel import WaitingListRightPanelProvider
from .services import (
    WaitingListValidationError,
    create_entry,
    transition_entry,
    update_entry,
)


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


class WaitingListValidationTests(TestCase):
    """Tests for server-side validation in services."""

    def setUp(self):
        self.user = User.objects.create_user(username="valuser", password="pass")

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


class WaitingListPolicyTests(TestCase):
    """Tests for waiting list policy layer."""

    def setUp(self):
        self.user = User.objects.create_user(username="policyuser", password="pass")
        self.manager = User.objects.create_user(username="manager", password="pass")
        self.outsider = User.objects.create_user(username="outsider", password="pass")
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        self.manager.groups.add(manager_group)

        self.entry = create_entry(
            author=self.user,
            patient_name="Пациент",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )

    def test_authenticated_user_can_view(self):
        self.assertTrue(can_view_waiting_list(self.user))

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


class WaitingListRouteTests(TestCase):
    """Tests for waiting list routes and HTMX behavior."""

    def setUp(self):
        self.user = User.objects.create_user(username="routeuser", password="pass")
        self.entry = create_entry(
            author=self.user,
            patient_name="Маршрутный Пациент",
            patient_dob="15.04.1985",
            patient_phone="+7 (903) 123-45-67",
            service_id="s1",
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("waiting_list:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_returns_200_for_authenticated(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("waiting_list:dashboard"))
        self.assertEqual(response.status_code, 200)

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
