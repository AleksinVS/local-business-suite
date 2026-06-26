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


class MedicalDeviceGroupingTests(TestCase):
    """Проверяет рендер списка медизделий со сворачиваемыми группами по подразделениям."""

    def setUp(self):
        self.manager = User.objects.create_user(username="chief2", password="pass")
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        self.manager.groups.add(manager_group)

        self.parent = Department.objects.create(name="Диагностический блок")
        self.child_a = Department.objects.create(name="Кабинет-А", parent=self.parent)
        self.child_b = Department.objects.create(name="Кабинет-Б", parent=self.parent)
        self.unrelated = Department.objects.create(name="Терапия")

        self.device_parent = MedicalDevice.objects.create(
            name="МРТ Siemens",
            inventory_number="104-1000",
            department=self.parent,
            operational_status=OperationalStatus.ACTIVE,
        )
        self.device_a = MedicalDevice.objects.create(
            name="Флюорограф Philips",
            inventory_number="104-1001",
            department=self.child_a,
            operational_status=OperationalStatus.ACTIVE,
        )
        self.device_b = MedicalDevice.objects.create(
            name="Сонограф GE",
            inventory_number="104-1002",
            department=self.child_b,
            operational_status=OperationalStatus.ACTIVE,
        )
        self.device_unrelated = MedicalDevice.objects.create(
            name="Измеритель АД",
            inventory_number="104-1003",
            department=self.unrelated,
            operational_status=OperationalStatus.ACTIVE,
        )

    def test_list_groups_devices_by_department(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        # Один <details class="device-group"> на каждый реальный департамент с изделиями.
        self.assertContains(response, '<details class="device-group"', count=4)
        # Каждое подразделение появляется как заголовок группы (через full_name).
        self.assertContains(response, self.parent.full_name)
        self.assertContains(response, self.child_a.full_name)
        self.assertContains(response, self.child_b.full_name)
        self.assertContains(response, self.unrelated.full_name)

    def test_group_summary_shows_device_count(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        # Каждая из четырёх групп имеет бейдж с числом 1.
        self.assertContains(
            response, '<span class="device-group-count">1</span>', count=4
        )
        # Добавим второе изделие в child_a — счётчик обновится.
        MedicalDevice.objects.create(
            name="Флюорограф",
            inventory_number="104-1100",
            department=self.child_a,
            operational_status=OperationalStatus.ACTIVE,
        )
        response = self.client.get(reverse("inventory:list"))
        self.assertContains(
            response, '<span class="device-group-count">2</span>', count=1
        )
        self.assertContains(
            response, '<span class="device-group-count">1</span>', count=3
        )

    def test_group_uses_full_name_for_hierarchical_title(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        expected_title = f"{self.parent.full_name} / {self.child_a.name}"
        self.assertContains(response, expected_title)

    def test_department_filter_yields_subtree_groups(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("inventory:list"), {"department": str(self.parent.pk)}
        )
        self.assertEqual(response.status_code, 200)
        # Фильтр по parent оставляет три группы (parent, child_a, child_b).
        self.assertContains(response, '<details class="device-group"', count=3)
        # Изделие из unrelated-подразделения не отображается в группах.
        self.assertNotContains(response, self.device_unrelated.name)
        # Группа с id несвязанного подразделения не появляется.
        self.assertNotContains(
            response, 'data-department-id="{}"'.format(self.unrelated.pk)
        )

    def test_archived_filter_respected_within_groups(self):
        self.device_a.archive()
        self.client.force_login(self.manager)
        # Без archived=1 архивное изделие не отображается.
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.device_a.name)
        # С archived=1 архивное появляется в своей группе.
        response = self.client.get(reverse("inventory:list"), {"archived": "1"})
        self.assertContains(response, self.device_a.name)

    def test_groups_open_by_default(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        # Атрибут open присутствует у каждой группы (рендеринг рядом с class).
        self.assertContains(response, '<details class="device-group" data-department-id', status_code=200)
        self.assertContains(response, " open>", count=4)

    def test_mass_controls_rendered(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Развернуть все")
        self.assertContains(response, "Свернуть все")
        self.assertContains(response, 'data-inventory-action="expand"')
        self.assertContains(response, 'data-inventory-action="collapse"')
        self.assertContains(response, "Найдено:")

    def test_per_row_actions_still_rendered(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/inventory/{}/'.format(self.device_a.pk))
        self.assertContains(
            response,
            'action="/inventory/{}/archive/"'.format(self.device_a.pk),
        )
        self.assertContains(response, "Изменить")
        self.assertContains(response, "Архивировать")

    def test_empty_result_shows_empty_state(self):
        MedicalDevice.objects.all().delete()
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "device-group")
        self.assertContains(response, "Записи не найдены.")

    def test_total_devices_count_shown(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Найдено: 4")

    def test_search_filter_still_works_with_groups(self):
        # Добавим изделие с уникальным рег. номером в существующее подразделение.
        MedicalDevice.objects.create(
            name="Электрокардиограф",
            inventory_number="104-9000",
            registration_certificate_number="РЗН 2030/00001",
            department=self.unrelated,
            operational_status=OperationalStatus.ACTIVE,
        )
        self.client.force_login(self.manager)
        response = self.client.get(reverse("inventory:list"), {"q": "РЗН 2030/00001"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Электрокардиограф")
        # Только одна группа содержит совпадение.
        self.assertContains(response, '<details class="device-group"', count=1)
        self.assertContains(
            response, '<span class="device-group-count">1</span>', count=1
        )
