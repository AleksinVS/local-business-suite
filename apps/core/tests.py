from django.contrib.auth.models import Group, User
from django.test import TestCase
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
