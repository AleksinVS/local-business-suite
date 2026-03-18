from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Department
from apps.workorders.policies import ROLE_MANAGER

from .models import MedicalDevice, OperationalStatus


class MedicalDeviceCrudTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="chief", password="pass")
        self.regular_user = User.objects.create_user(username="viewer", password="pass")
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        self.manager.groups.add(manager_group)
        self.department = Department.objects.create(name="Лучевая диагностика")
        self.device = MedicalDevice.objects.create(
            name="Рентген",
            serial_number="INV-001",
            department=self.department,
            operational_status=OperationalStatus.ACTIVE,
        )

    def test_regular_user_cannot_open_create_form(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse("inventory:create"))
        self.assertEqual(response.status_code, 403)

    def test_manager_can_edit_device(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("inventory:edit", args=[self.device.pk]),
            {
                "name": "Рентгеновский аппарат",
                "manufacturer": "",
                "model": "",
                "serial_number": "INV-001",
                "inventory_number": "",
                "department": self.department.pk,
                "location": "",
                "operational_status": OperationalStatus.MAINTENANCE,
                "commissioned_at": "",
                "notes": "Плановое ТО",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.device.refresh_from_db()
        self.assertEqual(self.device.name, "Рентгеновский аппарат")
        self.assertEqual(self.device.operational_status, OperationalStatus.MAINTENANCE)

    def test_manager_can_archive_device(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("inventory:archive", args=[self.device.pk]))
        self.assertEqual(response.status_code, 302)
        self.device.refresh_from_db()
        self.assertTrue(self.device.is_archived)
        self.assertIsNotNone(self.device.archived_at)

    def test_archived_device_hidden_by_default(self):
        self.device.archive()
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Рентген")

    def test_archived_device_visible_with_filter(self):
        self.device.archive()
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"), {"archived": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Рентген")

    def test_inventory_department_filter_uses_hierarchy(self):
        parent = Department.objects.create(name="Диагностический блок")
        child = Department.objects.create(name="Рентген-кабинет", parent=parent)
        hierarchical_device = MedicalDevice.objects.create(
            name="КТ",
            serial_number="INV-002",
            department=child,
            operational_status=OperationalStatus.ACTIVE,
        )
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"), {"department": parent.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, hierarchical_device.name)
