import json
import tempfile
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.workorders.policies import ROLE_MANAGER
from .models import Department


class DepartmentModelTests(TestCase):
    def test_full_name_and_descendants_follow_hierarchy(self):
        root = Department.objects.create(name="Стационар")
        child = Department.objects.create(name="Кардиология", parent=root)
        grandchild = Department.objects.create(name="Палата интенсивной терапии", parent=child)

        self.assertEqual(str(grandchild), "Стационар / Кардиология / Палата интенсивной терапии")
        self.assertEqual(set(root.descendant_ids()), {root.id, child.id, grandchild.id})


class DepartmentViewTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager-ui", password="pass")
        self.staff = User.objects.create_user(username="staff-ui", password="pass", is_staff=True)
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        self.manager.groups.add(manager_group)
        self.department = Department.objects.create(name="Стационар")

    def test_manager_can_open_department_directory(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("core:department_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Подразделения")

    def test_manager_can_create_child_department(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("core:department_create"),
            {"name": "ОРИТ", "parent": self.department.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Department.objects.filter(name="ОРИТ", parent=self.department).exists())

    def test_department_nav_link_visible_for_manager(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, reverse("core:department_list"))

    def test_admin_link_visible_for_staff(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, reverse("admin:index"))

    @override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=Path("/tmp/nonexistent-role-rules.json"))
    def test_manager_can_open_role_rules_editor(self):
        Path("/tmp/nonexistent-role-rules.json").write_text('{"manager": {"view_scope": "all", "create_workorder": true, "edit_scope": "all", "comment_scope": "visible", "upload_attachment_scope": "visible", "confirm_closure_scope": "all", "rate_scope": "all", "transition_scope": "all", "transition_targets": "*", "manage_inventory": true, "manage_board_columns": true, "manage_assignments": true}}', encoding="utf-8")
        self.client.force_login(self.manager)
        response = self.client.get(reverse("core:role_rules"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Права ролей")

    def test_manager_can_save_role_rules_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "role_rules.json"
            initial_payload = {
                "manager": {
                    "view_scope": "all",
                    "create_workorder": True,
                    "edit_scope": "all",
                    "comment_scope": "visible",
                    "upload_attachment_scope": "visible",
                    "confirm_closure_scope": "all",
                    "rate_scope": "all",
                    "transition_scope": "all",
                    "transition_targets": "*",
                    "manage_inventory": True,
                    "manage_board_columns": True,
                    "manage_assignments": True,
                }
            }
            config_path.write_text(json.dumps(initial_payload), encoding="utf-8")
            with override_settings(
                LOCAL_BUSINESS_ROLE_RULES_FILE=config_path,
                LOCAL_BUSINESS_ROLE_RULES=initial_payload,
            ):
                self.client.force_login(self.manager)
                updated_payload = {
                    "dispatcher": {
                        "view_scope": "all",
                        "create_workorder": True,
                        "edit_scope": "none",
                        "comment_scope": "visible",
                        "upload_attachment_scope": "none",
                        "confirm_closure_scope": "none",
                        "rate_scope": "none",
                        "transition_scope": "all",
                        "transition_targets": ["accepted"],
                        "manage_inventory": False,
                        "manage_board_columns": False,
                        "manage_assignments": False,
                    }
                }
                response = self.client.post(
                    reverse("core:role_rules"),
                    {"rules_json": json.dumps(updated_payload)},
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(json.loads(config_path.read_text(encoding="utf-8")), updated_payload)
