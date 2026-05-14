from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Department
from apps.inventory.models import MedicalDevice
from apps.workorders.models import Board, WorkOrder, WorkOrderStatus
from apps.workorders.policies import ROLE_MANAGER

User = get_user_model()


class AnalyticsDashboardTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Приемное отделение")
        self.device = MedicalDevice.objects.create(
            name="Дефибриллятор",
            serial_number="SN-003",
            department=self.department,
        )
        self.manager = User.objects.create_user(username="chief", password="pass")
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        self.manager.groups.add(manager_group)
        self.user = User.objects.create_user(username="guest", password="pass")
        self.board = Board.objects.create(title="Test Board", slug="test-board-analytics")
        WorkOrder.objects.create(
            title="Плановое ТО",
            description="Проверка питания.",
            department=self.department,
            author=self.manager,
            board=self.board,
            device=self.device,
            status=WorkOrderStatus.RESOLVED,
        )

    def test_manager_can_view_analytics_dashboard(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("analytics:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сводка по заявкам")

    def test_regular_user_cannot_view_analytics_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("analytics:dashboard"))
        self.assertEqual(response.status_code, 403)
