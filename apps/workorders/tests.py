from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Department
from apps.inventory.models import MedicalDevice

from .models import Board, KanbanColumnConfig, WorkOrder, WorkOrderAttachment, WorkOrderComment, WorkOrderStatus
from .policies import (
    ROLE_CUSTOMER,
    ROLE_MANAGER,
    ROLE_TECHNICIAN,
    can_confirm_closure,
    can_rate,
    can_transition,
    can_view,
)
from .right_panel import WorkOrderRightPanelProvider
from .services import confirm_closure, transition_workorder

User = get_user_model()


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

        self.board = Board.objects.create(title="Test Board", slug="test-board-1")
        self.board.allowed_groups.add(manager_group, tech_group, customer_group)
        self.workorder = WorkOrder.objects.create(
            title="Проверить датчик",
            description="Нестабильные показания.",
            department=self.department,
            author=self.customer,
            board=self.board,
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

    def test_default_workflow_allows_non_terminal_status_jumps_for_manager(self):
        self.assertTrue(can_transition(self.manager, self.workorder, WorkOrderStatus.IN_PROGRESS))
        self.assertTrue(can_transition(self.manager, self.workorder, WorkOrderStatus.RESOLVED))

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

    @override_settings(
        LOCAL_BUSINESS_ROLE_RULES={
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
                "view_analytics": False,
                "manage_departments": False,
                "manage_roles": False,
            }
        }
    )
    def test_transition_rights_can_come_from_settings_defined_role(self):
        dispatcher = User.objects.create_user(username="dispatcher", password="pass")
        dispatcher_group, _ = Group.objects.get_or_create(name="dispatcher")
        dispatcher.groups.add(dispatcher_group)

        self.assertTrue(can_view(dispatcher, self.workorder))
        self.assertTrue(can_transition(dispatcher, self.workorder, WorkOrderStatus.ACCEPTED))
        self.assertFalse(can_transition(dispatcher, self.workorder, WorkOrderStatus.IN_PROGRESS))

    @override_settings(
        LOCAL_BUSINESS_WORKFLOW_RULES={
            "statuses": [
                "new",
                "accepted",
                "in_progress",
                "on_hold",
                "resolved",
                "closed",
                "cancelled",
            ],
            "transitions": {
                "new": ["accepted"],
                "accepted": ["in_progress"],
                "in_progress": ["resolved"],
                "on_hold": [],
                "resolved": ["closed"],
                "closed": [],
                "cancelled": [],
            },
        }
    )
    def test_transition_matrix_can_come_from_workflow_config(self):
        self.assertTrue(can_transition(self.technician, self.workorder, WorkOrderStatus.ACCEPTED))
        self.assertFalse(can_transition(self.technician, self.workorder, WorkOrderStatus.CANCELLED))


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

        self.board = Board.objects.create(title="Test Board 2", slug="test-board-2")
        self.board.allowed_groups.add(manager_group, tech_group, customer_group)
        KanbanColumnConfig.objects.create(board=self.board, code="new", title="Новые", position=10, statuses=["new"])
        KanbanColumnConfig.objects.create(board=self.board, code="in_progress", title="В работе", position=20, statuses=["accepted", "in_progress", "on_hold"])
        KanbanColumnConfig.objects.create(board=self.board, code="done", title="Выполнены", position=30, statuses=["resolved"])
        KanbanColumnConfig.objects.create(board=self.board, code="archive", title="Архив", position=40, statuses=["closed", "cancelled"])
        self.workorder = WorkOrder.objects.create(
            title="Заменить кабель",
            description="Поврежден кабель питания.",
            department=self.sub_department,
            author=self.customer,
            board=self.board,
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
        self.assertContains(response, 'drawer-header')
        self.assertContains(response, self.workorder.title)

    def test_right_panel_provider_returns_descriptor_for_visible_workorder(self):
        provider = WorkOrderRightPanelProvider()

        descriptor = provider.build_panel(self.customer, str(self.workorder.pk))

        self.assertTrue(provider.can_open(self.customer, str(self.workorder.pk)))
        self.assertEqual(descriptor.source_code, "workorders")
        self.assertEqual(descriptor.object_type, "workorder")
        self.assertEqual(descriptor.object_id, str(self.workorder.pk))
        self.assertEqual(descriptor.drawer_size, "large")
        self.assertIn(reverse("workorders:detail", args=[self.workorder.pk]), descriptor.htmx_url)

    def test_right_panel_provider_denies_foreign_workorder(self):
        private_group, _ = Group.objects.get_or_create(name="private-right-panel")
        private_board = Board.objects.create(title="Private Board", slug="private-right-panel")
        private_board.allowed_groups.add(private_group)
        foreign = WorkOrder.objects.create(
            title="Чужая заявка",
            description="Недоступна",
            department=self.sub_department,
            author=self.manager,
            board=private_board,
        )
        provider = WorkOrderRightPanelProvider()

        self.assertFalse(provider.can_open(self.customer, str(foreign.pk)))

    def test_board_can_restore_empty_detail_panel(self):
        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("workorders:board"),
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="detail-panel",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Выбери карточку на доске")
        self.assertContains(response, "detail-panel-placeholder")

    def test_default_board_columns_are_configured(self):
        self.assertEqual(
            list(self.board.columns.values_list("title", flat=True)),
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

    def test_board_create_drawer_keeps_current_board(self):
        self.client.force_login(self.customer)
        response = self.client.get(
            f"{reverse('workorders:create')}?board={self.board.pk}",
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="detail-panel-content",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="board"')
        self.assertContains(response, f'value="{self.board.pk}"')

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
                "board": self.board.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        created = WorkOrder.objects.exclude(pk=self.workorder.pk).get()
        self.assertIsNone(created.assignee)
        self.assertEqual(created.author, self.customer)

    def test_customer_can_create_workorder_from_board_drawer(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("workorders:create"),
            {
                "title": "Заявка из канбана",
                "description": "Создана через правую панель.",
                "department": self.sub_department.pk,
                "priority": "medium",
                "device": "",
                "assignee": "",
                "board": self.board.pk,
            },
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="detail-panel-content",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response["HX-Redirect"],
            reverse("workorders:board_specific", kwargs={"board_slug": self.board.slug}),
        )
        created = WorkOrder.objects.exclude(pk=self.workorder.pk).get()
        self.assertEqual(created.title, "Заявка из канбана")
        self.assertEqual(created.board, self.board)
        self.assertEqual(created.author, self.customer)

    def test_customer_can_create_workorder_without_device(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("workorders:create"),
            {
                "title": "Починить раковину",
                "description": "Не уходит вода.",
                "department": self.sub_department.pk,
                "priority": "medium",
                "device": "",
                "assignee": "",
                "board": self.board.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        created = WorkOrder.objects.exclude(pk=self.workorder.pk).order_by("-pk").first()
        self.assertIsNone(created.device)

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
        column = KanbanColumnConfig.objects.get(code="new", board=self.board)
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
        column = KanbanColumnConfig.objects.get(code="new", board=self.board)
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:column_edit", args=[column.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="column-config-')
        self.assertContains(response, "Сохранить")

    def test_manager_can_restore_column_display_card(self):
        column = KanbanColumnConfig.objects.get(code="new", board=self.board)
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

    def test_board_search_matches_department_hierarchy(self):
        other_department = Department.objects.create(name="Администрация")
        WorkOrder.objects.create(
            title="Проверить сетевой принтер",
            description="Плановая проверка.",
            department=other_department,
            author=self.manager,
            board=self.board,
        )

        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:board"), {"q": self.department.name}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.workorder.title)
        self.assertNotContains(response, "Проверить сетевой принтер")

    def test_board_search_matches_author(self):
        WorkOrder.objects.create(
            title="Заявка другого заказчика",
            description="Не должна попасть в поиск.",
            department=self.department,
            author=self.manager,
            board=self.board,
        )

        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:board"), {"q": self.customer.username}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.workorder.title)
        self.assertNotContains(response, "Заявка другого заказчика")

    def test_board_search_matches_assignee_full_name(self):
        self.technician.first_name = "Илья"
        self.technician.last_name = "Иванов"
        self.technician.save(update_fields=["first_name", "last_name"])
        other_technician = User.objects.create_user(
            username="other_tech",
            first_name="Петр",
            last_name="Петров",
            password="pass",
        )
        WorkOrder.objects.create(
            title="Заявка другого исполнителя",
            description="Не должна попасть в поиск.",
            department=self.department,
            author=self.manager,
            assignee=other_technician,
            board=self.board,
        )

        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:board"), {"q": "Илья Иванов"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.workorder.title)
        self.assertNotContains(response, "Заявка другого исполнителя")


class StepperContextTests(TestCase):
    """Tests for _stepper_context and status_section template variables."""

    def setUp(self):
        self.department = Department.objects.create(name="Рентген")
        self.device = MedicalDevice.objects.create(
            name="Рентген-аппарат",
            serial_number="SN-X01",
            department=self.department,
        )
        self.customer = User.objects.create_user(username="cust_stepper", password="pass")
        self.technician = User.objects.create_user(username="tech_stepper", password="pass")
        self.manager = User.objects.create_user(username="mgr_stepper", password="pass")

        tech_group, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)

        self.technician.groups.add(tech_group)
        self.manager.groups.add(manager_group)
        self.customer.groups.add(customer_group)

        self.board = Board.objects.create(title="Stepper Board", slug="stepper-board")
        self.board.allowed_groups.add(manager_group, tech_group, customer_group)
        self.workorder = WorkOrder.objects.create(
            title="Stepper test",
            description="Testing stepper context.",
            department=self.department,
            author=self.customer,
            board=self.board,
            assignee=self.technician,
            device=self.device,
        )

    def test_detail_view_includes_stepper_context(self):
        self.client.force_login(self.technician)
        response = self.client.get(
            reverse("workorders:detail", args=[self.workorder.pk]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("transition_choices_vals", response.context)
        self.assertIn("status_choices", response.context)
        self.assertIsInstance(response.context["transition_choices_vals"], set)

    def test_transition_choices_vals_contains_only_allowed_transitions(self):
        self.client.force_login(self.technician)
        response = self.client.get(
            reverse("workorders:detail", args=[self.workorder.pk]),
        )
        vals = response.context["transition_choices_vals"]
        all_vals = {s for s, _ in WorkOrderStatus.choices}
        self.assertTrue(vals.issubset(all_vals))
        self.assertNotIn(WorkOrderStatus.NEW, vals)

    def test_htmx_transition_includes_stepper_context(self):
        self.client.force_login(self.technician)
        response = self.client.post(
            reverse("workorders:transition", args=[self.workorder.pk]),
            {"status": WorkOrderStatus.ACCEPTED},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("transition_choices_vals", response.context)
        self.assertIn("status_choices", response.context)

    def test_htmx_confirm_closure_includes_stepper_context(self):
        self.workorder.status = WorkOrderStatus.RESOLVED
        self.workorder.save()
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("workorders:confirm_closure", args=[self.workorder.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("transition_choices_vals", response.context)
        self.assertIn("status_choices", response.context)
        self.assertEqual(response.context["workorder"].status, WorkOrderStatus.CLOSED)
