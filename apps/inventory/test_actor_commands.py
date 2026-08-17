"""Проверки единой actor-aware границы изменения инвентаря."""

import json
import tempfile
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings

from apps.core.contract_store import _reset_for_tests, get_contract
from apps.core.models import Department

from .models import MedicalDevice
from .selectors import visible_devices_queryset
from .services import archive_device_command, update_device_command


User = get_user_model()


@pytest.mark.integration
class InventoryActorCommandTests(TestCase):
    def setUp(self):
        self.own_department = Department.objects.create(name="Свое подразделение")
        self.foreign_department = Department.objects.create(name="Чужое подразделение")
        self.actor = User.objects.create_user(
            username="inventory-command-actor",
            password="pass",
            department=self.own_department,
        )
        self.group = Group.objects.create(name="inventory-command-role")
        self.actor.groups.add(self.group)
        self.own_device = MedicalDevice.objects.create(
            name="Свое изделие", department=self.own_department
        )
        self.foreign_device = MedicalDevice.objects.create(
            name="Чужое изделие", department=self.foreign_department
        )
        payload = json.loads(json.dumps(get_contract("role_rules")))
        payload["inventory-command-role"] = {
            **payload["customer"],
            "view_scope": "department_branch",
            "manage_inventory": True,
        }
        self.tmpdir = tempfile.TemporaryDirectory()
        self.rules_path = Path(self.tmpdir.name) / "role_rules.json"
        self.rules_path.write_text(json.dumps(payload), encoding="utf-8")
        self.settings_context = override_settings(
            LOCAL_BUSINESS_ROLE_RULES_FILE=self.rules_path
        )
        self.settings_context.enable()
        _reset_for_tests()

    def tearDown(self):
        _reset_for_tests()
        self.settings_context.disable()
        self.tmpdir.cleanup()

    def test_foreign_update_and_archive_are_denied(self):
        with self.assertRaises(PermissionDenied):
            update_device_command(
                actor=self.actor,
                device_id=self.foreign_device.pk,
                payload={"name": "Нельзя"},
            )
        with self.assertRaises(PermissionDenied):
            archive_device_command(
                actor=self.actor,
                device_id=self.foreign_device.pk,
            )

    def test_role_revoke_is_rechecked_inside_command(self):
        self.actor.groups.remove(self.group)
        with self.assertRaises(PermissionDenied):
            update_device_command(
                actor=self.actor,
                device_id=self.own_device.pk,
                payload={"name": "Нельзя после отзыва"},
            )

    def test_device_selector_refreshes_stale_actor_after_department_change(self):
        self.assertIn(self.own_device, list(visible_devices_queryset(self.actor)))
        self.actor.department = self.foreign_department
        self.actor.save(update_fields=["department"])
        self.assertNotIn(self.own_device, list(visible_devices_queryset(self.actor)))
