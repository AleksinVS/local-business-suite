import csv
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import ANY, patch

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.json_utils import load_json_file
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
from .selectors import visible_waiting_list_entries
from .source_adapter import WaitingListSourceAdapter


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
class WaitingListDataCommandTests(TestCase):
    headers = (
        "Услуга",
        "ФИО",
        "Дата рождения",
        "Телефон",
        "Дата записи",
        "История изменений",
        "Дата бирки",
        "Дата окончания",
        "Cito",
        "Статус",
        "Комментарий",
        "Период",
    )

    def setUp(self):
        self.author = User.objects.create_user(
            username="waiting-list-importer",
            password="pass",
        )
        local_dir = Path(settings.BASE_DIR) / ".local"
        local_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = TemporaryDirectory(dir=local_dir)
        self.addCleanup(self.temp_dir.cleanup)

    def _write_export(self, *rows):
        path = Path(self.temp_dir.name) / "Выгрузка.txt"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.headers, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
        return path

    @staticmethod
    def _valid_row(**overrides):
        row = {
            "Услуга": "Катаракта",
            "ФИО": "Алексин Валентин Васильевич",
            "Дата рождения": "12.08.1946",
            "Телефон": "89005815724",
            "Дата записи": "11.11.2025 09:30:00",
            "История изменений": (
                "10.11.25 - Врач Тестовый - В очереди\n"
                "10.11.25 - Врач Тестовый - Назначена"
            ),
            "Дата бирки": "13.10.2027 8:29:59",
            "Дата окончания": "13.10.2027 9:29:59",
            "Cito": "Нет",
            "Статус": "Назначена",
            "Комментарий": "Исходный комментарий",
            "Период": "10.11.2025 10:27:02",
        }
        row.update(overrides)
        return row

    def test_import_command_preserves_fields_history_and_source_creation_time(self):
        path = self._write_export(self._valid_row())
        output = StringIO()

        call_command(
            "import_waiting_list",
            str(path),
            author=self.author.username,
            stdout=output,
        )

        entry = WaitingListEntry.objects.get()
        self.assertEqual(entry.author, self.author)
        self.assertEqual(entry.patient_dob, date(1946, 8, 12))
        self.assertEqual(entry.service_id, "s3")
        self.assertEqual(entry.status, WaitingListStatus.SCHEDULED)
        self.assertEqual(entry.date_tag, date(2027, 10, 13))
        self.assertEqual(entry.date_end, date(2027, 10, 13))
        self.assertFalse(entry.priority_cito)
        self.assertIn("Исходный комментарий", entry.comment)
        self.assertIn("Дата записи (импорт): 11.11.2025 09:30:00", entry.comment)
        self.assertEqual(
            timezone.localtime(entry.created_at).replace(tzinfo=None),
            datetime(2025, 11, 10, 10, 27, 2),
        )
        self.assertEqual(entry.audit_logs.count(), 2)
        self.assertTrue(
            entry.audit_logs.filter(action__contains="Врач Тестовый - Назначена").exists()
        )
        self.assertIn("записей=1", output.getvalue())

    def test_import_dry_run_validates_without_writing(self):
        WaitingListEntry.objects.create(
            author=self.author,
            patient_name="Существующий Пациент",
            patient_dob=date(1980, 1, 1),
            patient_phone="89000000000",
            service_id="s1",
        )
        path = self._write_export(self._valid_row())

        call_command(
            "import_waiting_list",
            str(path),
            author=self.author.username,
            dry_run=True,
            stdout=StringIO(),
        )

        self.assertEqual(WaitingListEntry.objects.count(), 1)

    def test_import_rejects_invalid_file_without_partial_writes(self):
        path = self._write_export(
            self._valid_row(),
            self._valid_row(**{"ФИО": "Ошибка Статуса", "Статус": "Неизвестен"}),
        )

        with self.assertRaisesMessage(CommandError, "строка 3"):
            call_command(
                "import_waiting_list",
                str(path),
                author=self.author.username,
                stdout=StringIO(),
            )

        self.assertFalse(WaitingListEntry.objects.exists())

    def test_import_requires_append_for_nonempty_list(self):
        WaitingListEntry.objects.create(
            author=self.author,
            patient_name="Существующий Пациент",
            patient_dob=date(1980, 1, 1),
            patient_phone="89000000000",
            service_id="s1",
        )
        path = self._write_export(self._valid_row())

        with self.assertRaisesMessage(CommandError, "--append"):
            call_command(
                "import_waiting_list",
                str(path),
                author=self.author.username,
                stdout=StringIO(),
            )

        self.assertEqual(WaitingListEntry.objects.count(), 1)

    def test_clear_dry_run_and_confirmation_guard(self):
        WaitingListEntry.objects.create(
            author=self.author,
            patient_name="Пациент Для Очистки",
            patient_dob=date(1980, 1, 1),
            patient_phone="89000000000",
            service_id="s1",
        )

        call_command("clear_waiting_list", dry_run=True, stdout=StringIO())
        self.assertEqual(WaitingListEntry.objects.count(), 1)
        with self.assertRaisesMessage(CommandError, "DELETE_WAITING_LIST"):
            call_command("clear_waiting_list", stdout=StringIO())
        self.assertEqual(WaitingListEntry.objects.count(), 1)

    def test_clear_removes_entries_and_audit_log(self):
        entry = WaitingListEntry.objects.create(
            author=self.author,
            patient_name="Пациент Для Удаления",
            patient_dob=date(1980, 1, 1),
            patient_phone="89000000000",
            service_id="s1",
        )
        WaitingListAuditLog.objects.create(
            entry=entry,
            actor=self.author,
            action="Тестовая история",
        )

        call_command(
            "clear_waiting_list",
            confirm="DELETE_WAITING_LIST",
            skip_projections=True,
            stdout=StringIO(),
        )

        self.assertFalse(WaitingListEntry.objects.exists())
        self.assertFalse(WaitingListAuditLog.objects.exists())

    @patch("apps.waiting_list.management.commands.clear_waiting_list.call_command")
    def test_clear_reconciles_derived_projections_by_default(self, reconcile):
        call_command(
            "clear_waiting_list",
            confirm="DELETE_WAITING_LIST",
            stdout=StringIO(),
        )

        reconcile.assert_called_once_with(
            "source_adapter_reconcile",
            source_code="waiting_list",
            target="all",
            backend="all",
            stdout=ANY,
            stderr=ANY,
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
        self.assertIn("ИВВИА", str(entry))

    def test_full_ophthalmology_service_catalog_includes_s4(self):
        self.assertEqual(
            SERVICE_CHOICES,
            [
                ("s1", "Амбул. операция (офт.)"),
                ("s2", "ИВВИА"),
                ("s3", "Катаракта"),
                ("s4", "Глаукома"),
            ],
        )
        entry = WaitingListEntry(
            patient_name="Тест каталога",
            patient_dob=date(1990, 1, 1),
            patient_phone="+7 (900) 000-00-00",
            service_id="s4",
        )
        entry.full_clean()
        self.assertEqual(entry.get_service_id_display(), "Глаукома")

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
        grant_doctor_role(user)
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
        grant_doctor_role(cls.user)

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

    def test_create_rechecks_actor_active_state_inside_service(self):
        stale_actor = User.objects.get(pk=self.user.pk)
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        with self.assertRaises(PermissionDenied):
            create_entry(
                author=stale_actor,
                patient_name="Неактивный Автор",
                patient_dob="01.01.1990",
                patient_phone="+7 (900) 111-22-33",
                service_id="s1",
            )

    def test_update_rechecks_actor_and_locked_entry(self):
        entry = create_entry(
            author=self.user,
            patient_name="Свежая Запись",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )
        stale_actor = User.objects.get(pk=self.user.pk)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            update_entry(entry=entry, user=stale_actor, patient_name="Не должно сохраниться")

        User.objects.filter(pk=self.user.pk).update(is_active=True)
        foreign = User.objects.create_user(username="fresh-foreign-author", password="pass")
        WaitingListEntry.objects.filter(pk=entry.pk).update(author=foreign)
        with self.assertRaises(PermissionDenied):
            update_entry(entry=entry, user=self.user, patient_name="Чужая запись")

    def test_transition_rechecks_actor_and_locked_entry(self):
        entry = create_entry(
            author=self.user,
            patient_name="Переходная Запись",
            patient_dob="01.01.1990",
            patient_phone="+7 (900) 111-22-33",
            service_id="s1",
        )
        stale_actor = User.objects.get(pk=self.user.pk)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            transition_entry(
                entry=entry,
                user=stale_actor,
                to_status=WaitingListStatus.SCHEDULED,
            )

        User.objects.filter(pk=self.user.pk).update(is_active=True)
        WaitingListEntry.objects.filter(pk=entry.pk).update(status=WaitingListStatus.CANCELLED)
        with self.assertRaises(PermissionDenied):
            transition_entry(
                entry=entry,
                user=self.user,
                to_status=WaitingListStatus.SCHEDULED,
            )


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

    def test_manager_cannot_edit_without_explicit_waiting_grant(self):
        rules = load_json_file("contracts/role_rules.json")
        self.assertFalse(
            can_edit_waiting_list_entry(
                self.manager,
                self.entry,
                rules_payload=rules,
            )
        )

    def test_outsider_cannot_edit(self):
        self.assertFalse(can_edit_waiting_list_entry(self.outsider, self.entry))

    def test_author_can_transition(self):
        self.assertTrue(can_transition_waiting_list_entry(self.user, self.entry))

    def test_manager_cannot_transition_without_explicit_waiting_grant(self):
        rules = load_json_file("contracts/role_rules.json")
        self.assertFalse(
            can_transition_waiting_list_entry(
                self.manager,
                self.entry,
                rules_payload=rules,
            )
        )

    def test_outsider_cannot_transition(self):
        self.assertFalse(can_transition_waiting_list_entry(self.outsider, self.entry))

    def test_legacy_superuser_default_and_active_roleless_profiles_fail_closed(self):
        legacy_rules = {
            "manager": {
                "manage_departments": True,
                "view_waiting_list": False,
                "create_waiting_list": False,
            },
            "legacy": {
                "view_waiting_list": True,
                "create_waiting_list": True,
            }
        }
        superuser = User.objects.create_superuser(username="legacy-root", password="pass")
        roleless = User.objects.create_user(username="roleless", password="pass")
        unknown_group_user = User.objects.create_user(username="unknown-role", password="pass")
        unknown_group, _ = Group.objects.get_or_create(name="future-role")
        unknown_group_user.groups.add(unknown_group)

        self.assertTrue(can_view_waiting_list(superuser, rules_payload=legacy_rules))
        self.assertTrue(can_create_waiting_list(superuser, rules_payload=legacy_rules))
        self.assertFalse(can_view_waiting_list(roleless, rules_payload=legacy_rules))
        self.assertFalse(can_view_waiting_list(unknown_group_user, rules_payload=legacy_rules))
        self.assertFalse(
            can_edit_waiting_list_entry(
                self.manager,
                self.entry,
                rules_payload=legacy_rules,
            )
        )
        self.assertTrue(
            can_transition_waiting_list_entry(
                superuser,
                self.entry,
                WaitingListStatus.SCHEDULED,
                rules_payload=legacy_rules,
            )
        )
        self.assertFalse(
            can_transition_waiting_list_entry(
                superuser,
                self.entry,
                WaitingListStatus.CONFIRMED,
                rules_payload=legacy_rules,
            )
        )

    def test_waiting_list_selector_uses_authored_scope_for_own_and_foreign_entries(self):
        rules = {
            "doctor": {
                "waiting_list_view_scope": "authored",
                "waiting_list_edit_scope": "none",
                "waiting_list_edit_statuses": [],
                "waiting_list_transition_scope": "none",
                "waiting_list_transition_from_statuses": [],
                "waiting_list_transition_targets": [],
            }
        }
        foreign = WaitingListEntry.objects.create(
            author=self.outsider,
            patient_name="Чужой Пациент",
            patient_dob=date(1990, 1, 1),
            patient_phone="+7 (900) 222-22-22",
            service_id="s1",
        )
        visible = visible_waiting_list_entries(self.user, rules_payload=rules)
        self.assertEqual(list(visible.values_list("pk", flat=True)), [self.entry.pk])
        self.assertNotIn(foreign.pk, visible.values_list("pk", flat=True))

    def test_waiting_policy_does_not_union_scope_and_status_from_different_roles(self):
        mixed_rules = {
            "broad_scope": {
                "waiting_list_view_scope": "all",
                "waiting_list_edit_scope": "all",
                "waiting_list_edit_statuses": ["waiting"],
                "waiting_list_transition_scope": "all",
                "waiting_list_transition_from_statuses": ["waiting"],
                "waiting_list_transition_targets": ["scheduled"],
            },
            "narrow_status": {
                "waiting_list_view_scope": "all",
                "waiting_list_edit_scope": "authored",
                "waiting_list_edit_statuses": ["scheduled"],
                "waiting_list_transition_scope": "authored",
                "waiting_list_transition_from_statuses": ["scheduled"],
                "waiting_list_transition_targets": ["confirmed"],
            },
        }
        self.user.groups.clear()
        self.user.groups.add(
            Group.objects.create(name="broad_scope"),
            Group.objects.create(name="narrow_status"),
        )
        self.entry.status = WaitingListStatus.SCHEDULED
        self.entry.author = self.outsider
        self.entry.save(update_fields=["status", "author"])

        self.assertFalse(
            can_edit_waiting_list_entry(self.user, self.entry, rules_payload=mixed_rules)
        )
        self.assertFalse(
            can_transition_waiting_list_entry(
                self.user,
                self.entry,
                WaitingListStatus.CONFIRMED,
                rules_payload=mixed_rules,
            )
        )

    def test_global_transition_graph_limits_superuser_for_every_status(self):
        superuser = User.objects.create_superuser(username="graph-root", password="pass")
        expected = {
            WaitingListStatus.WAITING: {WaitingListStatus.SCHEDULED, WaitingListStatus.CANCELLED},
            WaitingListStatus.SCHEDULED: {
                WaitingListStatus.WAITING,
                WaitingListStatus.CONFIRMED,
                WaitingListStatus.CANCELLED,
            },
            WaitingListStatus.CONFIRMED: {WaitingListStatus.CANCELLED},
            WaitingListStatus.CANCELLED: set(),
        }
        for status, targets in expected.items():
            entry = WaitingListEntry.objects.create(
                author=self.user,
                patient_name=f"Граф {status}",
                patient_dob=date(1990, 1, 1),
                patient_phone="+7 (900) 333-33-33",
                service_id="s1",
                status=status,
            )
            self.assertEqual(
                {
                    target
                    for target, _label in WaitingListStatus.choices
                    if can_transition_waiting_list_entry(superuser, entry, target)
                },
                targets,
            )

    def test_source_adapter_denies_foreign_entry(self):
        adapter = WaitingListSourceAdapter()
        self.assertFalse(adapter.can_access(self.outsider, str(self.entry.pk)))

    def test_right_panel_denies_foreign_entry(self):
        provider = WaitingListRightPanelProvider()
        self.assertFalse(provider.can_open(self.outsider, str(self.entry.pk)))
        with self.assertRaises(WaitingListEntry.DoesNotExist):
            provider.build_panel(self.outsider, str(self.entry.pk))


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

    def test_htmx_create_returns_event_without_redirect_or_full_page(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("waiting_list:create"),
            {
                "patient_name": "Новый HTMX Пациент",
                "patient_dob": "20.05.1980",
                "patient_phone": "+7 (905) 123-45-67",
                "service_id": "s2",
            },
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="entry-detail-panel-content",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["HX-Trigger"], "waitingListEntryCreated")
        self.assertNotIn("HX-Redirect", response.headers)
        self.assertEqual(response.content, b"")
        self.assertTrue(
            WaitingListEntry.objects.filter(patient_name="Новый HTMX Пациент").exists()
        )

    def test_htmx_create_validation_error_stays_in_drawer_form(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("waiting_list:create"),
            {
                "patient_name": "Новая запись с ошибкой",
                "patient_dob": "20.05.1980",
                "patient_phone": "123",
                "service_id": "s2",
            },
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="entry-detail-panel-content",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="waiting-list-form"')
        self.assertContains(response, "Неверный формат телефона")
        self.assertFalse(
            WaitingListEntry.objects.filter(patient_name="Новая запись с ошибкой").exists()
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

    def test_foreign_entry_is_hidden_or_forbidden_at_http_boundary(self):
        foreign_author = User.objects.create_user(username="route-foreign-author", password="pass")
        foreign = WaitingListEntry.objects.create(
            author=foreign_author,
            patient_name="Чужой Маршрут",
            patient_dob=date(1990, 1, 1),
            patient_phone="+7 (900) 444-44-44",
            service_id="s1",
        )
        authored_rules = {
            "doctor": {
                "waiting_list_view_scope": "authored",
                "waiting_list_edit_scope": "authored",
                "waiting_list_edit_statuses": ["waiting"],
                "waiting_list_transition_scope": "authored",
                "waiting_list_transition_from_statuses": ["waiting"],
                "waiting_list_transition_targets": ["scheduled"],
            }
        }
        self.client.force_login(self.user)
        with patch("apps.waiting_list.views._role_rules_snapshot", return_value=authored_rules):
            hidden = self.client.get(
                reverse("waiting_list:detail", kwargs={"pk": foreign.pk})
            )
        self.assertEqual(hidden.status_code, 404)

        viewer = User.objects.create_user(username="route-viewer", password="pass")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        viewer.groups.add(viewer_group)
        viewer_rules = {
            "viewer": {
                "waiting_list_view_scope": "all",
                "waiting_list_edit_scope": "none",
                "waiting_list_edit_statuses": [],
                "waiting_list_transition_scope": "none",
                "waiting_list_transition_from_statuses": [],
                "waiting_list_transition_targets": [],
            }
        }
        self.client.force_login(viewer)
        with patch("apps.waiting_list.views._role_rules_snapshot", return_value=viewer_rules):
            forbidden = self.client.post(
                reverse("waiting_list:update", kwargs={"pk": foreign.pk}),
                {
                    "patient_name": foreign.patient_name,
                    "patient_dob": "01.01.1990",
                    "patient_phone": foreign.patient_phone,
                    "service_id": foreign.service_id,
                },
            )
        self.assertEqual(forbidden.status_code, 403)
