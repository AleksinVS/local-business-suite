"""Регрессии на actor-aware read adapters AI."""

import json
import tempfile
from pathlib import Path

import pytest
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings

from apps.core.contract_store import _reset_for_tests, get_contract
from apps.core.models import Department
from apps.inventory.selectors import visible_devices_queryset as visible_inventory_devices_queryset
from apps.inventory.models import MedicalDevice
from apps.workorders.models import Board, WorkOrder
from apps.workorders.selectors import (
    creation_departments_queryset,
    creation_devices_queryset,
    resource_visibility_mode,
    visible_departments_queryset,
)

from ..services import (
    archive_device_for_actor,
    create_device_for_actor,
    create_workorder_for_actor,
    get_analytics_summary_for_actor,
    get_role_rules_for_actor,
    get_workorder_for_actor,
    list_departments_for_actor,
    list_devices_for_actor,
    list_groups_for_actor,
    list_users_for_actor,
    update_device_for_actor,
)

User = get_user_model()


@pytest.mark.integration
class ScopedReadServiceTests(TestCase):
    def test_access_catalog_reads_recheck_actor_and_product_authority(self):
        ordinary = User.objects.create_user(username="ai-access-ordinary", password="pass")
        manager = User.objects.create_user(username="ai-access-manager", password="pass")
        manager_role, _ = Group.objects.get_or_create(name="manager")
        manager.groups.add(manager_role)
        root = User.objects.create_superuser(
            username="ai-access-root",
            password="pass",
            email="root@example.test",
        )

        with self.assertRaises(PermissionDenied):
            get_role_rules_for_actor(actor=ordinary, payload={})
        self.assertIn("rules", get_role_rules_for_actor(actor=manager, payload={}))
        self.assertTrue(list_users_for_actor(actor=root, payload={})["items"])
        self.assertIn("manager", list_groups_for_actor(actor=root, payload={})["items"])

        root.is_active = False
        root.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            list_users_for_actor(actor=root, payload={})
        with self.assertRaises(PermissionDenied):
            list_groups_for_actor(actor=root, payload={})

        manager.is_active = False
        manager.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            get_role_rules_for_actor(actor=manager, payload={})

    def test_ai_reads_use_the_same_relational_scope_and_fail_closed_for_inactive(self):
        own_department = Department.objects.create(name="AI своя ветка")
        foreign_department = Department.objects.create(name="AI чужая ветка")
        own_device = MedicalDevice.objects.create(
            name="AI видимое изделие",
            inventory_number="AI-OWN",
            department=own_department,
        )
        foreign_device = MedicalDevice.objects.create(
            name="AI чужое изделие",
            inventory_number="AI-FOREIGN",
            department=foreign_department,
        )
        actor = User.objects.create_user(
            username="ai-scoped-reader",
            password="pass",
            department=own_department,
        )
        other = User.objects.create_user(username="ai-other", password="pass")
        role_group, _ = Group.objects.get_or_create(name="ai-scoped-reader")
        actor.groups.add(role_group)
        board = Board.objects.create(title="AI scoped board", slug="ai-scoped-board")
        board.allowed_groups.add(role_group)
        own = WorkOrder.objects.create(
            title="AI связанная заявка",
            description="Видима актору.",
            department=own_department,
            author=other,
            assignee=actor,
            board=board,
            device=own_device,
        )
        foreign = WorkOrder.objects.create(
            title="AI чужая заявка",
            description="Не видима актору.",
            department=foreign_department,
            author=other,
            assignee=other,
            board=board,
            device=foreign_device,
        )
        role_rules = {
            "ai-scoped-reader": {
                **json.loads(json.dumps(get_contract("role_rules")["technician"])),
                "view_scope": "assigned",
                "view_analytics": True,
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path

            role_rules_path = Path(tmpdir) / "role_rules.json"
            role_rules_path.write_text(json.dumps(role_rules), encoding="utf-8")
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=role_rules_path):
                _reset_for_tests()
                try:
                    departments = list_departments_for_actor(actor=actor)
                    devices = list_devices_for_actor(actor=actor)
                    summary = get_analytics_summary_for_actor(
                        actor=actor,
                        payload={"summary_type": "status"},
                    )

                    self.assertEqual(
                        {item["id"] for item in departments},
                        {own_department.pk},
                    )
                    self.assertEqual(
                        {item["id"] for item in devices},
                        {own_device.pk},
                    )
                    self.assertEqual(summary["summary"], [{"status": own.status, "total": 1}])
                    with self.assertRaises(PermissionDenied):
                        get_workorder_for_actor(actor=actor, workorder_id=foreign.pk)
                finally:
                    _reset_for_tests()

        actor.is_active = False
        actor.save(update_fields=["is_active"])
        self.assertEqual(list_departments_for_actor(actor=actor), [])
        self.assertEqual(list_devices_for_actor(actor=actor), [])
        with self.assertRaises(PermissionDenied):
            get_analytics_summary_for_actor(
                actor=actor,
                payload={"summary_type": "status"},
            )

    def test_mixed_branch_and_assigned_roles_use_branch_resource_scope(self):
        root = Department.objects.create(name="AI mixed root")
        actor_department = Department.objects.create(name="AI mixed actor", parent=root)
        assigned_department = Department.objects.create(name="AI mixed assigned", parent=root)
        actor = User.objects.create_user(
            username="ai-mixed-scope",
            password="pass",
            department=root,
        )
        branch_group, _ = Group.objects.get_or_create(name="ai-mixed-branch")
        assigned_group, _ = Group.objects.get_or_create(name="ai-mixed-assigned")
        actor.groups.add(branch_group, assigned_group)
        payload = json.loads(json.dumps(get_contract("role_rules")))
        branch_role = dict(payload["customer"])
        branch_role["view_scope"] = "department_branch"
        assigned_role = dict(payload["technician"])
        assigned_role["view_scope"] = "assigned"
        payload.update(
            {
                "ai-mixed-branch": branch_role,
                "ai-mixed-assigned": assigned_role,
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            role_rules_path = Path(tmpdir) / "role_rules.json"
            role_rules_path.write_text(json.dumps(payload), encoding="utf-8")
            with override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=role_rules_path):
                _reset_for_tests()
                try:
                    self.assertEqual(resource_visibility_mode(actor), "branch")
                    self.assertEqual(
                        set(
                            visible_departments_queryset(actor)
                            .values_list("pk", flat=True)
                        ),
                        {root.pk, actor_department.pk, assigned_department.pk},
                    )
                finally:
                    _reset_for_tests()


@pytest.mark.integration
class ScopedMutationServiceTests(TestCase):
    def setUp(self):
        self.own_department = Department.objects.create(name="AI mutation own branch")
        self.foreign_department = Department.objects.create(name="AI mutation foreign branch")
        self.own_device = MedicalDevice.objects.create(
            name="AI mutation own device",
            inventory_number="AI-MUTATION-OWN",
            department=self.own_department,
        )
        self.foreign_device = MedicalDevice.objects.create(
            name="AI mutation foreign device",
            inventory_number="AI-MUTATION-FOREIGN",
            department=self.foreign_department,
        )
        self.actor = User.objects.create_user(
            username="ai-mutation-actor",
            password="pass",
            department=self.own_department,
        )
        self.role_group, _ = Group.objects.get_or_create(name="ai-mutation-manager")
        self.actor.groups.add(self.role_group)
        self.board, _ = Board.objects.get_or_create(
            slug="main",
            defaults={"title": "AI mutation board"},
        )
        self.board.allowed_groups.add(self.role_group)

    def _with_scoped_role_rules(self):
        payload = json.loads(json.dumps(get_contract("role_rules")))
        manager = dict(payload.get("manager", {}))
        manager.update(
            {
                "view_scope": "department_branch",
                "create_workorder": True,
                "manage_inventory": True,
            }
        )
        payload["ai-mutation-manager"] = manager
        tmpdir = tempfile.TemporaryDirectory()
        path = Path(tmpdir.name) / "role_rules.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return tmpdir, override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=path)

    def test_mutations_reject_foreign_department_device_and_mismatch(self):
        tmpdir, settings_context = self._with_scoped_role_rules()
        with tmpdir, settings_context:
            _reset_for_tests()
            try:
                with self.assertRaises(PermissionDenied):
                    create_workorder_for_actor(
                        actor=self.actor,
                        payload={
                            "department_id": self.foreign_department.pk,
                            "subject": "foreign department",
                            "description": "must fail",
                        },
                    )
                with self.assertRaises(PermissionDenied):
                    create_workorder_for_actor(
                        actor=self.actor,
                        payload={
                            "department_id": self.own_department.pk,
                            "device_id": self.foreign_device.pk,
                            "subject": "foreign device",
                            "description": "must fail",
                        },
                    )
                with self.assertRaises(PermissionDenied):
                    create_device_for_actor(
                        actor=self.actor,
                        payload={
                            "department_id": self.foreign_department.pk,
                            "name": "foreign device",
                        },
                    )
                with self.assertRaises(PermissionDenied):
                    update_device_for_actor(
                        actor=self.actor,
                        payload={
                            "device_id": self.foreign_device.pk,
                            "name": "must fail",
                        },
                    )
                with self.assertRaises(PermissionDenied):
                    archive_device_for_actor(
                        actor=self.actor,
                        payload={"device_id": self.foreign_device.pk},
                    )
            finally:
                _reset_for_tests()

    def test_mutation_rejects_mismatched_devices_when_both_departments_are_allowed(self):
        root = Department.objects.create(name="AI mutation shared root")
        first_department = Department.objects.create(name="AI mutation first", parent=root)
        second_department = Department.objects.create(name="AI mutation second", parent=root)
        first_device = MedicalDevice.objects.create(
            name="AI mutation first device",
            inventory_number="AI-MUTATION-FIRST",
            department=first_department,
        )
        second_device = MedicalDevice.objects.create(
            name="AI mutation second device",
            inventory_number="AI-MUTATION-SECOND",
            department=second_department,
        )
        self.actor.department = root
        self.actor.save(update_fields=["department"])
        tmpdir, settings_context = self._with_scoped_role_rules()
        with tmpdir, settings_context:
            _reset_for_tests()
            try:
                self.assertIn(
                    first_department.pk,
                    creation_departments_queryset(self.actor).values_list("pk", flat=True),
                )
                self.assertIn(
                    second_device.pk,
                    creation_devices_queryset(self.actor).values_list("pk", flat=True),
                )
                self.assertIn(
                    first_device.pk,
                    creation_devices_queryset(self.actor).values_list("pk", flat=True),
                )
                with self.assertRaises(PermissionDenied):
                    create_workorder_for_actor(
                        actor=self.actor,
                        payload={
                            "department_id": first_department.pk,
                            "device_id": second_device.pk,
                            "subject": "mismatched device",
                            "description": "must fail",
                        },
                    )
            finally:
                _reset_for_tests()

    def test_foreign_archived_device_is_not_selectable_or_mutable(self):
        self.foreign_device.archive()
        tmpdir, settings_context = self._with_scoped_role_rules()
        with tmpdir, settings_context:
            _reset_for_tests()
            try:
                self.assertNotIn(
                    self.foreign_device.pk,
                    visible_inventory_devices_queryset(
                        self.actor,
                        include_archived=True,
                    ).values_list("pk", flat=True),
                )
                with self.assertRaises(PermissionDenied):
                    archive_device_for_actor(
                        actor=self.actor,
                        payload={"device_id": self.foreign_device.pk},
                    )
            finally:
                _reset_for_tests()

    def test_mutation_rechecks_revoked_actor_inside_transaction(self):
        tmpdir, settings_context = self._with_scoped_role_rules()
        with tmpdir, settings_context:
            _reset_for_tests()
            try:
                self.actor.groups.remove(self.role_group)
                with self.assertRaises(PermissionDenied):
                    create_device_for_actor(
                        actor=self.actor,
                        payload={
                            "department_id": self.own_department.pk,
                            "name": "revoked actor device",
                        },
                    )
                self.actor.groups.add(self.role_group)
                self.actor.is_active = False
                self.actor.save(update_fields=["is_active"])
                with self.assertRaises(PermissionDenied):
                    archive_device_for_actor(
                        actor=self.actor,
                        payload={"device_id": self.own_device.pk},
                    )
            finally:
                _reset_for_tests()
