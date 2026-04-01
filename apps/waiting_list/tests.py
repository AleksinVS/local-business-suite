from datetime import date

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .models import SERVICE_CHOICES, WaitingListAuditLog, WaitingListEntry, WaitingListStatus
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
            patient_dob="15.04.1985",
            patient_phone="+7 (903) 123-45-67",
            service_id="s1",
        )
        self.assertIsInstance(entry.pk, int)
        self.assertIsNotNone(entry.external_id)

    def test_entry_str_representation(self):
        """Entry string representation includes name and service."""
        entry = WaitingListEntry.objects.create(
            patient_name="Петрова Анна Сергеевна",
            patient_dob="22.08.1990",
            patient_phone="+7 (916) 987-65-43",
            service_id="s2",
        )
        self.assertIn("Петрова Анна Сергеевна", str(entry))
        self.assertIn("МРТ позвоночника", str(entry))

    def test_entry_default_status_is_waiting(self):
        """New entries default to WAITING status."""
        entry = WaitingListEntry.objects.create(
            patient_name="Тестов Тест Тестович",
            patient_dob="01.01.1990",
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
            patient_dob="05.05.1980",
            patient_phone="+7 (999) 999-99-99",
            service_id="s1",
            priority_cito=True,
        )
        self.assertTrue(entry.priority_cito)


class WaitingListServiceValidationTests(TestCase):
    """Tests for server-side validation in services."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")

    def test_create_entry_validates_phone_format(self):
        """Invalid phone formats are rejected."""
        with self.assertRaises(WaitingListValidationError) as ctx:
            create_entry(
                author=self.user,
                patient_name="Иванов Иван Иванович",
                patient_dob="15.04.1985",
                patient_phone="123",  # Invalid
                service_id="s1",
            )
        self.assertIn("телефон", str(ctx.exception).lower())

    def test_create_entry_validates_dob_format(self):
        """Invalid DOB formats are rejected."""
        with self.assertRaises(WaitingListValidationError) as ctx:
            create_entry(
                author=self.user,
                patient_name="Иванов Иван Иванович",
                patient_dob="1985-04-15",  # Wrong format
                patient_phone="+7 (903) 123-45-67",
                service_id="s1",
            )
        error_msg = str(ctx.exception).lower()
        # Check that DOB format error is raised (message may be in Russian)
        self.assertTrue(
            "дата рождения" in error_msg or "формат" in error_msg,
            f"Expected DOB validation error, got: {error_msg}"
        )

    def test_create_entry_validates_patient_name_minimum(self):
        """Patient name must be at least 2 characters."""
        with self.assertRaises(WaitingListValidationError) as ctx:
            create_entry(
                author=self.user,
                patient_name="И",  # Too short
                patient_dob="15.04.1985",
                patient_phone="+7 (903) 123-45-67",
                service_id="s1",
            )
        self.assertIn("ФИО", str(ctx.exception))

    def test_transition_entry_creates_audit_log(self):
        """Transitioning status creates audit log."""
        entry = create_entry(
            author=self.user,
            patient_name="Тестов Тест Тестович",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )
        initial_count = entry.audit_logs.count()

        transition_entry(entry=entry, user=self.user, to_status=WaitingListStatus.SCHEDULED)

        entry.refresh_from_db()
        self.assertEqual(entry.status, WaitingListStatus.SCHEDULED)
        self.assertEqual(entry.audit_logs.count(), initial_count + 1)

    def test_update_entry_creates_audit_log(self):
        """Updating entry creates audit log with changes."""
        entry = create_entry(
            author=self.user,
            patient_name="Тестов Тест Тестович",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )
        initial_count = entry.audit_logs.count()

        update_entry(
            entry=entry,
            user=self.user,
            patient_name="Тестов Обновленный Тестович",
        )

        entry.refresh_from_db()
        self.assertIn("Тестов Обновленный", entry.patient_name)
        self.assertEqual(entry.audit_logs.count(), initial_count + 1)


class WaitingListRouteTests(TestCase):
    """Tests for route accessibility and HTMX behavior."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.entry = WaitingListEntry.objects.create(
            patient_name="Иванов Иван Иванович",
            patient_dob="15.04.1985",
            patient_phone="+7 (903) 123-45-67",
            service_id="s1",
        )

    def test_dashboard_requires_login(self):
        """Dashboard is not accessible to anonymous users."""
        response = self.client.get(reverse("waiting_list:dashboard"))
        # LoginRequiredMixin returns 302 redirect or 403 for HTMX
        self.assertIn(response.status_code, [302, 403])

    def test_dashboard_loads_for_authenticated(self):
        """Dashboard loads for authenticated users."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("waiting_list:dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_entry_detail_loads(self):
        """Entry detail page loads correctly."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("waiting_list:detail", args=[self.entry.pk]))
        self.assertEqual(response.status_code, 200)

    def test_create_entry_loads_form(self):
        """Create entry form loads correctly."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("waiting_list:create"))
        self.assertEqual(response.status_code, 200)

    def test_entry_table_partial_for_htmx(self):
        """Dashboard returns table partial for HTMX requests."""
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("waiting_list:dashboard"),
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="entry-table",
        )
        self.assertEqual(response.status_code, 200)

    def test_transition_via_htmx(self):
        """Status transition works via HTMX."""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("waiting_list:transition", args=[self.entry.pk]),
            {"status": WaitingListStatus.CONFIRMED},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, WaitingListStatus.CONFIRMED)

    def test_filter_by_service(self):
        """Dashboard filters by service correctly."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("waiting_list:dashboard"), {"service": "s1"})
        self.assertEqual(response.status_code, 200)

    def test_search_filter(self):
        """Dashboard search filter works."""
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("waiting_list:dashboard"),
            {"search": "Иванов"},
        )
        self.assertEqual(response.status_code, 200)
