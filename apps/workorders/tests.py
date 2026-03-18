from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Department
from apps.inventory.models import MedicalDevice

from .models import KanbanColumnConfig, WorkOrder, WorkOrderAttachment, WorkOrderComment, WorkOrderStatus
from .policies import (
    ROLE_CUSTOMER,
    ROLE_MANAGER,
    ROLE_TECHNICIAN,
    can_confirm_closure,
    can_rate,
    can_transition,
    can_view,
)
from .services import confirm_closure, transition_workorder


class WorkOrderRoleMatrixTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Диагностика")
        self.device = MedicalDevice.objects.create(
            name="УЗИ аппарат",
            serial_number="SN-001",
            department=self.department,
        )
        self.customer = User.objects.create_user(username="customer", password="pass")
        self.technician = User.objects.create_user(username="tech", password="pass")
        self.manager = User.objects.create_user(username="manager", password="pass")
        self.outsider = User.objects.create_user(username="outsider", password="pass")

        tech_group, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)

        self.technician.groups.add(tech_group)
        self.manager.groups.add(manager_group)
        self.customer.groups.add(customer_group)

        self.workorder = WorkOrder.objects.create(
            title="Проверить датчик",
            description="Нестабильные показания.",
            department=self.department,
            author=self.customer,
            assignee=self.technician,
            device=self.device,
        )

    def test_customer_and_manager_can_view_workorder(self):
        self.assertTrue(can_view(self.customer, self.workorder))
        self.assertTrue(can_view(self.manager, self.workorder))

    def test_assigned_technician_can_view_workorder(self):
        self.assertTrue(can_view(self.technician, self.workorder))

    def test_outsider_cannot_view_workorder(self):
        self.assertFalse(can_view(self.outsider, self.workorder))

    def test_customer_cannot_move_workorder_to_in_progress(self):
        self.assertFalse(can_transition(self.customer, self.workorder, WorkOrderStatus.IN_PROGRESS))

    def test_technician_can_move_workorder_through_technical_statuses(self):
        self.workorder.status = WorkOrderStatus.ACCEPTED
        self.workorder.save()
        self.assertTrue(can_transition(self.technician, self.workorder, WorkOrderStatus.IN_PROGRESS))

    def test_customer_can_confirm_closure_only_after_resolved(self):
        self.assertFalse(can_confirm_closure(self.customer, self.workorder))
        self.workorder.status = WorkOrderStatus.RESOLVED
        self.workorder.save()
        self.assertTrue(can_confirm_closure(self.customer, self.workorder))

    def test_confirm_closure_sets_confirmation_fields(self):
        self.workorder.status = WorkOrderStatus.RESOLVED
        self.workorder.save()
        confirm_closure(workorder=self.workorder, user=self.customer)
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.status, WorkOrderStatus.CLOSED)
        self.assertTrue(self.workorder.closure_confirmed)
        self.assertIsNotNone(self.workorder.closure_confirmed_at)
        self.assertTrue(can_rate(self.customer, self.workorder))

    def test_transition_service_creates_audit_log(self):
        transition_workorder(
            workorder=self.workorder,
            user=self.technician,
            to_status=WorkOrderStatus.ACCEPTED,
        )
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.status, WorkOrderStatus.ACCEPTED)
        self.assertEqual(self.workorder.transitions.count(), 1)

    def test_workorder_number_is_human_readable(self):
        self.assertEqual(self.workorder.number, str(self.workorder.pk))


class WorkOrderViewPermissionTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Стационар")
        self.sub_department = Department.objects.create(name="ОРИТ", parent=self.department)
        self.device = MedicalDevice.objects.create(
            name="Монитор пациента",
            serial_number="SN-002",
            department=self.sub_department,
        )
        self.customer = User.objects.create_user(username="customer2", password="pass")
        self.technician = User.objects.create_user(username="tech2", password="pass")
        self.manager = User.objects.create_user(username="manager2", password="pass")
        self.outsider = User.objects.create_user(username="outsider2", password="pass")

        tech_group, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)

        self.technician.groups.add(tech_group)
        self.manager.groups.add(manager_group)
        self.customer.groups.add(customer_group)

        self.workorder = WorkOrder.objects.create(
            title="Заменить кабель",
            description="Поврежден кабель питания.",
            department=self.sub_department,
            author=self.customer,
            assignee=self.technician,
            device=self.device,
        )

    def test_outsider_cannot_open_detail(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("workorders:detail", args=[self.workorder.pk]))
        self.assertEqual(response.status_code, 404)

    def test_outsider_does_not_see_board_cards(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("workorders:board"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.workorder.title)

    def test_board_detail_panel_renders_partial_for_htmx(self):
        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("workorders:detail", args=[self.workorder.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="detail-panel"')
        self.assertContains(response, self.workorder.title)

    def test_board_can_restore_empty_detail_panel(self):
        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("workorders:board"),
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="detail-panel",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Выбери карточку на доске")
        self.assertContains(response, "is-hidden")

    def test_default_board_columns_are_configured(self):
        self.assertEqual(
            list(KanbanColumnConfig.objects.values_list("title", flat=True)),
            ["Новые", "В работе", "Выполнены", "Архив"],
        )

    def test_board_uses_request_number_in_card_title(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("workorders:board"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.workorder.number}. Заменить кабель")
        self.assertContains(response, 'name="status"')
        self.assertContains(response, 'hx-trigger="change"')
        self.assertContains(response, 'data-column-code="')

    def test_technician_can_move_card_to_other_column(self):
        self.client.force_login(self.technician)
        response = self.client.post(
            reverse("workorders:board_move", args=[self.workorder.pk]),
            {"column": "in_progress"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="board-columns",
        )
        self.assertEqual(response.status_code, 200)
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.status, WorkOrderStatus.ACCEPTED)

    def test_customer_cannot_drag_card_to_technical_column(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("workorders:board_move", args=[self.workorder.pk]),
            {"column": "in_progress"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="board-columns",
        )
        self.assertEqual(response.status_code, 403)

    def test_customer_can_create_workorder(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("workorders:create"),
            {
                "title": "Новая заявка",
                "description": "Описание",
                "department": self.sub_department.pk,
                "priority": "medium",
                "device": self.device.pk,
                "assignee": self.technician.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        created = WorkOrder.objects.exclude(pk=self.workorder.pk).get()
        self.assertIsNone(created.assignee)
        self.assertEqual(created.author, self.customer)

    def test_outsider_cannot_create_workorder(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("workorders:create"))
        self.assertEqual(response.status_code, 403)

    def test_technician_cannot_edit_customer_owned_workorder(self):
        self.client.force_login(self.technician)
        response = self.client.post(
            reverse("workorders:edit", args=[self.workorder.pk]),
            {
                "title": "Чужое изменение",
                "description": self.workorder.description,
                "department": self.workorder.department.pk,
                "priority": self.workorder.priority,
                "device": self.device.pk,
                "assignee": self.technician.pk,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_assigned_technician_can_comment(self):
        self.client.force_login(self.technician)
        response = self.client.post(
            reverse("workorders:comment", args=[self.workorder.pk]),
            {"body": "Начал диагностику."},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkOrderComment.objects.count(), 1)

    def test_outsider_cannot_comment(self):
        self.client.force_login(self.outsider)
        response = self.client.post(
            reverse("workorders:comment", args=[self.workorder.pk]),
            {"body": "Лишний комментарий"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 404)

    def test_outsider_cannot_upload_attachment(self):
        self.client.force_login(self.outsider)
        upload = SimpleUploadedFile("photo.jpg", b"filecontent", content_type="image/jpeg")
        response = self.client.post(
            reverse("workorders:attachment", args=[self.workorder.pk]),
            {"file": upload},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(WorkOrderAttachment.objects.count(), 0)

    def test_customer_cannot_jump_to_accepted_transition(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("workorders:transition", args=[self.workorder.pk]),
            {"status": WorkOrderStatus.ACCEPTED},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)

    def test_technician_can_transition_assigned_workorder(self):
        self.client.force_login(self.technician)
        response = self.client.post(
            reverse("workorders:transition", args=[self.workorder.pk]),
            {"status": WorkOrderStatus.ACCEPTED},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.status, WorkOrderStatus.ACCEPTED)

    def test_board_quick_transition_returns_board_partial(self):
        self.client.force_login(self.technician)
        response = self.client.post(
            reverse("workorders:transition", args=[self.workorder.pk]),
            {"status": WorkOrderStatus.ACCEPTED},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="board-columns",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="board-columns"')
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.status, WorkOrderStatus.ACCEPTED)

    def test_manager_can_rename_column_title(self):
        column = KanbanColumnConfig.objects.get(code="new")
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("workorders:column_rename", args=[column.pk]),
            {"title": "Свежие заявки"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        column.refresh_from_db()
        self.assertEqual(column.title, "Свежие заявки")
        self.assertContains(response, "Свежие заявки")

    def test_manager_can_open_inline_column_edit_form(self):
        column = KanbanColumnConfig.objects.get(code="new")
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:column_edit", args=[column.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="column-config-')
        self.assertContains(response, "Сохранить")

    def test_manager_can_restore_column_display_card(self):
        column = KanbanColumnConfig.objects.get(code="new")
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:column_display", args=[column.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Переименовать")

    def test_workorder_detail_no_longer_shows_author_field(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("workorders:detail", args=[self.workorder.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<strong>Автор:</strong>", html=True)

    def test_customer_can_confirm_closure_and_rate(self):
        self.workorder.status = WorkOrderStatus.RESOLVED
        self.workorder.save()
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("workorders:confirm_closure", args=[self.workorder.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.status, WorkOrderStatus.CLOSED)

        response = self.client.post(
            reverse("workorders:rate", args=[self.workorder.pk]),
            {"rating": 5},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.rating, 5)

    def test_technician_cannot_rate_closed_workorder(self):
        self.workorder.status = WorkOrderStatus.RESOLVED
        self.workorder.save()
        confirm_closure(workorder=self.workorder, user=self.customer)
        self.client.force_login(self.technician)
        response = self.client.post(
            reverse("workorders:rate", args=[self.workorder.pk]),
            {"rating": 4},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)

    def test_attachment_validation_still_works(self):
        self.client.force_login(self.technician)
        upload = SimpleUploadedFile("archive.zip", b"zipcontent", content_type="application/zip")
        response = self.client.post(
            reverse("workorders:attachment", args=[self.workorder.pk]),
            {"file": upload},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Недопустимый тип файла.", status_code=400)

    def test_board_department_filter_uses_hierarchy(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("workorders:board"), {"department": self.department.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.workorder.title)
