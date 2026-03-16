from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.inventory.models import MedicalDevice

from .models import WorkOrder, WorkOrderAttachment, WorkOrderComment, WorkOrderStatus
from .policies import ROLE_MANAGER, ROLE_TECHNICIAN, can_transition
from .services import transition_workorder


class WorkOrderPolicyTests(TestCase):
    def setUp(self):
        self.device = MedicalDevice.objects.create(
            name="УЗИ аппарат",
            serial_number="SN-001",
            department="Диагностика",
        )
        self.author = User.objects.create_user(username="author", password="pass")
        self.technician = User.objects.create_user(username="tech", password="pass")
        self.manager = User.objects.create_user(username="manager", password="pass")
        tech_group, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        self.technician.groups.add(tech_group)
        self.manager.groups.add(manager_group)
        self.workorder = WorkOrder.objects.create(
            title="Проверить датчик",
            description="Нестабильные показания.",
            department="Диагностика",
            author=self.author,
            device=self.device,
        )

    def test_technician_can_accept_new_workorder(self):
        self.assertTrue(can_transition(self.technician, self.workorder, WorkOrderStatus.ACCEPTED))

    def test_manager_can_close_resolved_workorder(self):
        self.workorder.status = WorkOrderStatus.RESOLVED
        self.workorder.save()
        self.assertTrue(can_transition(self.manager, self.workorder, WorkOrderStatus.CLOSED))

    def test_transition_service_creates_audit_log(self):
        transition_workorder(
            workorder=self.workorder,
            user=self.technician,
            to_status=WorkOrderStatus.ACCEPTED,
        )
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.status, WorkOrderStatus.ACCEPTED)
        self.assertEqual(self.workorder.transitions.count(), 1)


class WorkOrderHtmxTests(TestCase):
    def setUp(self):
        self.device = MedicalDevice.objects.create(
            name="Монитор пациента",
            serial_number="SN-002",
            department="ОРИТ",
        )
        self.user = User.objects.create_user(username="tech2", password="pass")
        tech_group, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        self.user.groups.add(tech_group)
        self.workorder = WorkOrder.objects.create(
            title="Заменить кабель",
            description="Поврежден кабель питания.",
            department="ОРИТ",
            author=self.user,
            device=self.device,
        )

    def test_htmx_comment_returns_partial(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("workorders:comment", args=[self.workorder.pk]),
            {"body": "Начал диагностику."},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Начал диагностику.")
        self.assertEqual(WorkOrderComment.objects.count(), 1)

    def test_htmx_attachment_uploads_file(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile("photo.jpg", b"filecontent", content_type="image/jpeg")
        response = self.client.post(
            reverse("workorders:attachment", args=[self.workorder.pk]),
            {"file": upload},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkOrderAttachment.objects.count(), 1)

    def test_htmx_transition_returns_status_partial(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("workorders:transition", args=[self.workorder.pk]),
            {"status": WorkOrderStatus.ACCEPTED},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Принята")
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.status, WorkOrderStatus.ACCEPTED)
