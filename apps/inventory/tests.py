from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Department
from apps.workorders.policies import ROLE_MANAGER

from .models import MedicalDevice, OperationalStatus

User = get_user_model()


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
            inventory_number="104-0001",
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
                "device_type": "Рентгеновский аппарат",
                "manufacturer": "Siemens",
                "production_country": "Германия",
                "model": "YSIO Max",
                "serial_number": "INV-001",
                "inventory_number": "104-0001",
                "registration_date": "2020-03-15",
                "registration_certificate_number": "РЗН 2020/12000",
                "production_date": "2019-11-01",
                "commissioned_at": "2020-04-01",
                "service_life_years": 10,
                "department": self.department.pk,
                "address": "Корпус А - 2 - 205",
                "location": "",
                "operational_status": OperationalStatus.MAINTENANCE,
                "decommissioned_at": "",
                "decommission_reason": "",
                "notes": "Плановое ТО",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.device.refresh_from_db()
        self.assertEqual(self.device.name, "Рентгеновский аппарат")
        self.assertEqual(self.device.operational_status, OperationalStatus.MAINTENANCE)
        self.assertEqual(self.device.device_type, "Рентгеновский аппарат")
        self.assertEqual(self.device.manufacturer, "Siemens")
        self.assertEqual(self.device.production_country, "Германия")
        self.assertEqual(self.device.registration_certificate_number, "РЗН 2020/12000")
        self.assertEqual(self.device.service_life_years, 10)
        self.assertEqual(self.device.address, "Корпус А - 2 - 205")

    def test_decommission_fields_saved(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("inventory:edit", args=[self.device.pk]),
            {
                "name": self.device.name,
                "device_type": "",
                "manufacturer": "",
                "production_country": "",
                "model": "",
                "serial_number": self.device.serial_number,
                "inventory_number": "",
                "registration_date": "",
                "registration_certificate_number": "",
                "production_date": "",
                "commissioned_at": "",
                "service_life_years": "",
                "department": self.department.pk,
                "address": "",
                "location": "",
                "operational_status": OperationalStatus.DECOMMISSIONED,
                "decommissioned_at": "2025-09-01",
                "decommission_reason": "Истёк срок службы",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.device.refresh_from_db()
        self.assertEqual(self.device.operational_status, OperationalStatus.DECOMMISSIONED)
        self.assertEqual(self.device.decommissioned_at.isoformat(), "2025-09-01")
        self.assertEqual(self.device.decommission_reason, "Истёк срок службы")

    def test_search_finds_by_registration_certificate(self):
        MedicalDevice.objects.create(
            name="Электрокардиограф",
            serial_number="INV-100",
            inventory_number="104-0100",
            registration_certificate_number="РЗН 2021/99999",
            department=self.department,
            operational_status=OperationalStatus.ACTIVE,
        )
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"), {"q": "РЗН 2021/99999"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Электрокардиограф")

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
            inventory_number="104-0002",
            department=child,
            operational_status=OperationalStatus.ACTIVE,
        )
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"), {"department": parent.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, hierarchical_device.name)

    def test_list_renders_new_columns_and_detail_link(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Тип")
        self.assertContains(response, "Рег. №")
        self.assertContains(response, "Размещение")
        self.assertContains(response, '/inventory/{}/'.format(self.device.pk))

    def test_detail_view_renders_all_field_groups(self):
        self.device.device_type = "Рентгеновский аппарат"
        self.device.manufacturer = "Siemens"
        self.device.production_country = "Германия"
        self.device.registration_certificate_number = "РЗН 2020/12000"
        self.device.address = "Корпус А - 2 - 205"
        self.device.save()
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:detail", args=[self.device.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.device.name)
        self.assertContains(response, self.device.serial_number)
        self.assertContains(response, "Рентгеновский аппарат")
        self.assertContains(response, "Siemens")
        self.assertContains(response, "Германия")
        self.assertContains(response, "РЗН 2020/12000")
        self.assertContains(response, "Корпус А")
        self.assertContains(response, "205")
        self.assertContains(response, "Основное")
        self.assertContains(response, "Регистрационные данные")
        self.assertContains(response, "Размещение")
        self.assertContains(response, "Эксплуатация")

    def test_detail_view_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("inventory:detail", args=[self.device.pk]))
        self.assertEqual(response.status_code, 302)

    def test_form_renders_grouped_sections(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:edit", args=[self.device.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Основное")
        self.assertContains(response, "Регистрационные данные")
        self.assertContains(response, "Размещение")
        self.assertContains(response, "Эксплуатация")
        self.assertContains(response, "Номер регистрационного удостоверения")
        self.assertContains(response, "Срок службы")
