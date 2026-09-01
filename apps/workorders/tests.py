import json
import copy
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.core.models import Department
from apps.inventory.models import MedicalDevice
from apps.notifications.models import NotificationRecipient


@contextmanager
def _override_contract_file(setting_name, filename, payload):
    """Пишет payload во временный файл и указывает на него *_FILE-настройку.

    После ADR-0031 политики читают контракты через contract store (файл), а не
    через ``settings.LOCAL_BUSINESS_*`` payload-константу, поэтому тестовые
    подмены должны переопределять путь к файлу и сбрасывать кэш store.
    """
    from apps.core.contract_store import _reset_for_tests

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / filename
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with override_settings(**{setting_name: path}):
            _reset_for_tests()
            try:
                yield path
            finally:
                _reset_for_tests()

import apps.core.json_utils as json_utils
from apps.core.contract_store import get_contract

from .department_filter import (
    build_department_filter_read_model,
    normalize_department_ids,
    normalize_device_ids,
    resolve_department_device_selection,
    resolve_department_selection,
)
from .models import Board, BoardAccessAudit, KanbanColumnConfig, WorkOrder, WorkOrderAttachment, WorkOrderComment, WorkOrderStatus
from .policies import (
    ROLE_CUSTOMER,
    ROLE_MANAGER,
    ROLE_TECHNICIAN,
    can_comment,
    can_confirm_closure,
    can_create,
    can_edit,
    can_rate,
    can_transition,
    can_view,
    active_role_rules,
    capability_flags,
    default_board_access_applies,
    has_role_capability,
    superuser_rules,
)
from .selectors import (
    creation_departments_queryset,
    visible_boards_queryset,
    visible_departments_queryset,
    visible_devices_queryset,
    visible_workorders_queryset,
)
from .right_panel import WorkOrderRightPanelProvider
from .services import (
    apply_board_access,
    clone_board,
    _confirm_closure_unchecked,
    _create_workorder_unchecked,
    initialize_board_access_for_bootstrap,
    preview_board_access,
    _board_access_user_ids,
    _transition_workorder_unchecked,
)
from .contracts import validate_role_rules_payload

User = get_user_model()


@pytest.mark.unit
class WorkOrderStatusColorStyleTests(SimpleTestCase):
    def test_board_style_uses_runtime_palette(self):
        from .views import _workorder_status_color_style

        payload = json_utils.load_json_file("contracts/workorder_status_colors.json")
        payload["statuses"]["new"]["color"] = "#123456"
        with _override_contract_file(
            "LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE",
            "workorder_status_colors.json",
            payload,
        ):
            style = _workorder_status_color_style()

        self.assertIn("--workorder-status-new: #123456", style)
        self.assertIn("--workorder-status-new-bg:", style)


@pytest.mark.unit
class BoardAdminAccessTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_superuser(
            username="board-admin",
            password="pass",
            email="board-admin@example.test",
        )
        self.customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)
        self.technician_group, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        self.board = Board.objects.create(title="Ресурсная доска", slug="resource-board")
        self.board.allowed_groups.add(self.customer_group)

    def test_allowed_groups_are_read_only_in_django_admin_form(self):
        from django.contrib import admin
        from django.test import RequestFactory

        from .admin import BoardAdmin

        request = RequestFactory().get("/admin/workorders/board/add/")
        request.user = self.actor

        form_class = BoardAdmin(Board, admin.site).get_form(request)

        self.assertNotIn("allowed_groups", form_class.base_fields)

    def test_workorder_and_board_hard_delete_are_denied_even_for_superuser(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from .admin import BoardAdmin, WorkOrderAdmin

        request = RequestFactory().get("/admin/workorders/")
        request.user = self.actor
        workorder_admin = WorkOrderAdmin(WorkOrder, admin.site)
        board_admin = BoardAdmin(Board, admin.site)
        self.assertFalse(workorder_admin.has_delete_permission(request))
        self.assertFalse(board_admin.has_delete_permission(request))

    def test_seed_board_clear_fails_closed_and_keeps_existing_workorders(self):
        department = Department.objects.create(name="Seed command department")
        workorder = WorkOrder.objects.create(
            board=self.board,
            title="Не удалять",
            description="Доменная отмена вместо удаления",
            department=department,
            author=self.actor,
        )
        with self.assertRaises(CommandError):
            call_command("seed_board", "--clear", "--board-slug", self.board.slug)
        self.assertTrue(WorkOrder.objects.filter(pk=workorder.pk).exists())

    def test_board_access_service_previews_applies_and_changes_visibility(self):
        technician = User.objects.create_user(username="board-tech", password="pass")
        technician.groups.add(self.technician_group)
        self.assertFalse(visible_boards_queryset(technician).filter(pk=self.board.pk).exists())

        preview = preview_board_access(
            actor=self.actor,
            board=self.board,
            selected_group_names=[ROLE_CUSTOMER, ROLE_TECHNICIAN],
        )
        board, audit = apply_board_access(
            actor=self.actor,
            board=self.board,
            selected_group_names=[ROLE_CUSTOMER, ROLE_TECHNICIAN],
            preview_token=preview["preview_token"],
            risk_confirmed=True,
        )

        self.assertEqual(audit.groups_added, [ROLE_TECHNICIAN])
        self.assertEqual(audit.source, BoardAccessAudit.Source.SETTINGS_CENTER)
        self.assertEqual(audit.reason, "")
        self.assertTrue(visible_boards_queryset(technician).filter(pk=board.pk).exists())

    def test_roleless_user_is_not_counted_in_customer_board_access_impact(self):
        roleless = User.objects.create_user(username="roleless-board-user", password="pass")
        self.assertNotIn(roleless.pk, _board_access_user_ids([ROLE_CUSTOMER]))

    def test_removal_requires_confirmation_and_unknown_group_is_rejected(self):
        self.board.allowed_groups.add(self.technician_group)
        preview = preview_board_access(
            actor=self.actor,
            board=self.board,
            selected_group_names=[ROLE_CUSTOMER],
            reason="Убрать доступ техников",
        )
        with self.assertRaisesMessage(ValidationError, "подтверждения риска"):
            apply_board_access(
                actor=self.actor,
                board=self.board,
                selected_group_names=[ROLE_CUSTOMER],
                preview_token=preview["preview_token"],
                reason="Убрать доступ техников",
            )
        self.assertTrue(self.board.allowed_groups.filter(name=ROLE_TECHNICIAN).exists())
        with self.assertRaisesMessage(ValidationError, "недопустимы группы"):
            preview_board_access(
                actor=self.actor,
                board=self.board,
                selected_group_names=[ROLE_CUSTOMER, "memory_auditor"],
                reason="Проверка неизвестной группы",
            )

    def test_board_access_break_glass_requires_reason(self):
        with self.assertRaisesMessage(ValidationError, "резервного изменения"):
            preview_board_access(
                actor=self.actor,
                board=self.board,
                selected_group_names=[ROLE_CUSTOMER, ROLE_TECHNICIAN],
                source=BoardAccessAudit.Source.DJANGO_ADMIN_BREAK_GLASS,
            )

    def test_board_impact_excludes_roleless_user_and_rejects_stale_population(self):
        roleless = User.objects.create_user(username="board-roleless-default")
        preview = preview_board_access(
            actor=self.actor,
            board=self.board,
            selected_group_names=[ROLE_TECHNICIAN],
            reason="Закрыть базовый доступ заказчика",
        )
        self.assertFalse(default_board_access_applies(roleless))

        late_technician = User.objects.create_user(username="board-late-technician")
        late_technician.groups.add(self.technician_group)
        with self.assertRaisesMessage(ValidationError, "Состав сотрудников"):
            apply_board_access(
                actor=self.actor,
                board=self.board,
                selected_group_names=[ROLE_TECHNICIAN],
                preview_token=preview["preview_token"],
                risk_confirmed=True,
                reason="Закрыть базовый доступ заказчика",
            )
        self.assertTrue(roleless.is_active)

    def test_board_preview_rejects_lifecycle_change_before_apply(self):
        from apps.accounts.services import disable_local_user

        technician = User.objects.create_user(username="board-lifecycle-technician")
        technician.groups.add(self.technician_group)
        preview = preview_board_access(
            actor=self.actor,
            board=self.board,
            selected_group_names=[ROLE_CUSTOMER, ROLE_TECHNICIAN],
            reason="Добавить техников после проверки состава",
        )
        lifecycle_operator = User.objects.create_superuser(username="board-lifecycle-root")
        disable_local_user(actor=lifecycle_operator, user=technician)

        with self.assertRaisesMessage(ValidationError, "Состав сотрудников"):
            apply_board_access(
                actor=self.actor,
                board=self.board,
                selected_group_names=[ROLE_CUSTOMER, ROLE_TECHNICIAN],
                preview_token=preview["preview_token"],
                risk_confirmed=True,
                reason="Добавить техников после проверки состава",
            )
        self.assertFalse(self.board.allowed_groups.filter(name=ROLE_TECHNICIAN).exists())

    def test_django_admin_break_glass_uses_service_and_domain_audit(self):
        self.board.allowed_groups.add(self.technician_group)
        self.client.force_login(self.actor)
        url = reverse("admin:workorders_board_access", args=[self.board.pk])
        page = self.client.get(url)
        self.assertContains(page, 'value="preview"', html=False)
        self.assertNotContains(page, 'value="save"', html=False)
        response = self.client.post(
            url,
            {"action": "preview", "group_names": [ROLE_CUSTOMER], "reason": "Аварийный отзыв"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Проверка изменения")
        self.assertContains(response, 'value="apply"', html=False)
        preview = response.context["preview"]
        response = self.client.post(
            url,
            {
                "action": "apply",
                "group_names": [ROLE_CUSTOMER],
                "reason": "Аварийный отзыв",
                "preview_token": preview["preview_token"],
                "risk_confirmed": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        audit = BoardAccessAudit.objects.get(board=self.board)
        self.assertEqual(audit.source, BoardAccessAudit.Source.DJANGO_ADMIN_BREAK_GLASS)
        self.assertEqual(audit.reason, "Аварийный отзыв")

    def test_clone_service_requires_separate_access_assignment(self):
        cloned = clone_board(actor=self.actor, board=self.board, reason="Резервная копия")
        self.assertFalse(cloned.allowed_groups.exists())
        self.assertFalse(BoardAccessAudit.objects.filter(board=cloned).exists())

    def test_clone_without_actor_fails_closed(self):
        with self.assertRaises(PermissionDenied):
            self.board.clone()

    def test_system_bootstrap_allows_only_preexisting_canonical_empty_boards_once(self):
        for slug in ("main", "backlog"):
            with self.subTest(slug=slug):
                canonical, _created = Board.objects.get_or_create(
                    slug=slug,
                    defaults={"title": f"Каноническая доска {slug}"},
                )
                canonical.allowed_groups.clear()
                BoardAccessAudit.objects.filter(board=canonical).delete()

                canonical, audit = initialize_board_access_for_bootstrap(
                    board=canonical,
                    selected_group_names=[ROLE_CUSTOMER],
                    reason=f"Инициализация канонической доски {slug}.",
                    board_was_created=False,
                )
                _canonical, repeated_audit = initialize_board_access_for_bootstrap(
                    board=canonical,
                    selected_group_names=[ROLE_CUSTOMER],
                    reason=f"Повторная инициализация канонической доски {slug}.",
                    board_was_created=False,
                )

                self.assertEqual(
                    set(canonical.allowed_groups.values_list("name", flat=True)),
                    {ROLE_CUSTOMER},
                )
                self.assertEqual(audit.source, BoardAccessAudit.Source.SYSTEM_BOOTSTRAP)
                self.assertIsNone(repeated_audit)
                self.assertEqual(
                    BoardAccessAudit.objects.filter(
                        board=canonical,
                        source=BoardAccessAudit.Source.SYSTEM_BOOTSTRAP,
                    ).count(),
                    1,
                )

        arbitrary = Board.objects.create(title="Пустая рабочая доска", slug="empty-real-board")
        with self.assertRaisesMessage(ValidationError, "канонической системной доски"):
            initialize_board_access_for_bootstrap(
                board=arbitrary,
                selected_group_names=[ROLE_CUSTOMER],
                reason="Недопустимый bootstrap.",
                board_was_created=False,
            )
        self.assertFalse(arbitrary.allowed_groups.exists())
        self.assertFalse(BoardAccessAudit.objects.filter(board=arbitrary).exists())

    def test_inactive_user_cannot_see_board_names(self):
        user = User.objects.create_user(username="inactive-board-user", is_active=False)
        user.groups.add(self.customer_group)

        self.assertFalse(visible_boards_queryset(user).exists())

    def test_actor_privilege_change_after_preview_fails_closed(self):
        preview = preview_board_access(
            actor=self.actor,
            board=self.board,
            selected_group_names=[ROLE_CUSTOMER, ROLE_TECHNICIAN],
            reason="Проверка смены полномочий.",
        )
        self.actor.is_superuser = False
        self.actor.save(update_fields=["is_superuser"])

        with self.assertRaises(PermissionDenied):
            apply_board_access(
                actor=self.actor,
                board=self.board,
                selected_group_names=[ROLE_CUSTOMER, ROLE_TECHNICIAN],
                preview_token=preview["preview_token"],
                risk_confirmed=True,
                reason="Проверка смены полномочий.",
            )

    def test_degraded_role_contract_blocks_board_access_preview(self):
        from apps.core.contract_store import get_contract
        from apps.core.json_utils import load_json_file

        payload = load_json_file("contracts/role_rules.json")
        with _override_contract_file(
            "LOCAL_BUSINESS_ROLE_RULES_FILE",
            "role_rules.json",
            payload,
        ) as role_path:
            get_contract("role_rules")
            role_path.write_text("{broken", encoding="utf-8")
            get_contract("role_rules")

            with self.assertRaisesMessage(ValidationError, "режиме деградации"):
                preview_board_access(
                    actor=self.actor,
                    board=self.board,
                    selected_group_names=[ROLE_CUSTOMER, ROLE_TECHNICIAN],
                    reason="Не должно примениться.",
                )


@pytest.mark.unit
class DepartmentFilterReadModelTests(SimpleTestCase):
    def setUp(self):
        self.departments = (
            SimpleNamespace(id=1, parent_id=None, name="Корпус А"),
            SimpleNamespace(id=2, parent_id=1, name="Отделение А"),
            SimpleNamespace(id=3, parent_id=2, name="Кабинет А"),
            SimpleNamespace(id=4, parent_id=None, name="Корпус Б"),
            SimpleNamespace(id=5, parent_id=4, name="Отделение Б"),
        )

    def test_normalizer_keeps_visible_positive_ids_and_absorbs_descendant(self):
        normalized = normalize_department_ids(
            ["3", "1", "5", "3", "bad", "0", "999"],
            self.departments,
        )

        self.assertEqual(normalized, (1, 5))

    def test_selection_expands_only_visible_descendants(self):
        selection = resolve_department_selection(["2"], self.departments)

        self.assertEqual(selection.selected_ids, (2,))
        self.assertEqual(selection.branch_ids, frozenset({2, 3}))

    def test_read_model_supports_multiple_roots_and_deep_selection(self):
        rows = build_department_filter_read_model(
            self.departments,
            selected_ids=(3, 4),
        )

        self.assertEqual([row["id"] for row in rows], [1, 2, 3, 4, 5])
        self.assertEqual([row["level"] for row in rows], [0, 1, 2, 0, 1])
        self.assertTrue(rows[0]["ancestor_of_selected"])
        self.assertTrue(rows[1]["ancestor_of_selected"])
        self.assertTrue(rows[2]["selected"])
        self.assertTrue(rows[3]["selected"])
        self.assertEqual(
            set(rows[0]),
            {
                "kind",
                "key",
                "parent_key",
                "department_id",
                "id",
                "label",
                "parent_id",
                "level",
                "has_children",
                "selected",
                "ancestor_of_selected",
            },
        )

    def test_unified_read_model_appends_device_leaves_and_marks_ancestors(self):
        devices = (
            SimpleNamespace(
                id=11,
                department_id=3,
                name="Монитор",
                inventory_number="INV-11",
                __str__=lambda self: "Монитор · инв. INV-11",
            ),
            SimpleNamespace(
                id=12,
                department_id=999,
                name="Недоступный аппарат",
                inventory_number=None,
            ),
        )

        rows = build_department_filter_read_model(
            self.departments,
            selected_ids=(),
            visible_devices=devices,
            selected_device_ids=(11, 12, 999),
        )

        device_rows = [row for row in rows if row["kind"] == "device"]
        self.assertEqual([row["device_id"] for row in device_rows], [11])
        self.assertEqual(device_rows[0]["parent_key"], "department:3")
        self.assertTrue(device_rows[0]["selected"])
        self.assertFalse(device_rows[0]["has_children"])
        self.assertTrue(
            all(
                row["ancestor_of_selected"]
                for row in rows
                if row.get("department_id") in {1, 2, 3}
            )
        )

    def test_device_normalizer_and_selection_ignore_unknown_values(self):
        devices = (
            SimpleNamespace(id=10),
            SimpleNamespace(id=20),
        )

        self.assertEqual(
            normalize_device_ids(["20", "bad", "10", "20", "0", "999"], devices),
            (20, 10),
        )
        selection = resolve_department_device_selection(
            ["2"],
            ["20", "999"],
            self.departments,
            devices,
        )
        self.assertEqual(selection.selected_department_ids, (2,))
        self.assertEqual(selection.selected_device_ids, (20,))
        self.assertEqual(selection.selected_count, 2)

    def test_read_model_is_empty_for_empty_visible_queryset(self):
        self.assertEqual(build_department_filter_read_model((), ()), ())


@pytest.mark.integration
class WorkOrderRoleMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.department = Department.objects.create(name="Диагностика")
        cls.device = MedicalDevice.objects.create(
            name="УЗИ аппарат",
            serial_number="SN-001",
            department=cls.department,
        )
        cls.customer = User.objects.create_user(
            username="customer", password="pass", department=cls.department
        )
        cls.technician = User.objects.create_user(username="tech", password="pass")
        cls.manager = User.objects.create_user(username="manager", password="pass")
        cls.outsider = User.objects.create_user(username="outsider", password="pass")
        cls.default_viewer = User.objects.create_user(
            username="default-viewer",
            password="pass",
            department=cls.department,
        )

        tech_group, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)

        cls.technician.groups.add(tech_group)
        cls.manager.groups.add(manager_group)
        cls.customer.groups.add(customer_group)

        cls.board = Board.objects.create(title="Test Board", slug="test-board-1")
        cls.board.allowed_groups.add(manager_group, tech_group, customer_group)
        cls.workorder = WorkOrder.objects.create(
            title="Проверить датчик",
            description="Нестабильные показания.",
            department=cls.department,
            author=cls.customer,
            board=cls.board,
            assignee=cls.technician,
            device=cls.device,
        )

    def test_customer_and_manager_can_view_workorder(self):
        self.assertTrue(can_view(self.customer, self.workorder))
        self.assertTrue(can_view(self.manager, self.workorder))

    def test_user_without_role_has_no_workorder_access(self):
        self.assertFalse(default_board_access_applies(self.default_viewer))
        self.assertFalse(can_view(self.default_viewer, self.workorder))
        self.assertFalse(can_create(self.default_viewer))
        self.assertFalse(can_edit(self.default_viewer, self.workorder))
        self.assertFalse(can_comment(self.default_viewer, self.workorder))
        self.assertFalse(
            can_transition(
                self.default_viewer,
                self.workorder,
                WorkOrderStatus.ACCEPTED,
            )
        )

    def test_default_board_access_management_command_runs_and_rolls_back(self):
        call_command("default_board_access_e2e")

        self.assertFalse(
            User.objects.filter(
                username__startswith="__default_board_access_e2e_"
            ).exists()
        )

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
        _confirm_closure_unchecked(workorder=self.workorder, user=self.customer)
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.status, WorkOrderStatus.CLOSED)
        self.assertIsNotNone(self.workorder.resolved_at)
        self.assertIsNotNone(self.workorder.closed_at)
        self.assertTrue(self.workorder.closure_confirmed)
        self.assertIsNotNone(self.workorder.closure_confirmed_at)
        self.assertTrue(can_rate(self.customer, self.workorder))

    def test_save_sets_terminal_dates_when_created_closed(self):
        workorder = WorkOrder.objects.create(
            title="Закрытая заявка",
            description="Создана сразу закрытой.",
            department=self.department,
            author=self.customer,
            board=self.board,
            status=WorkOrderStatus.CLOSED,
        )

        self.assertIsNotNone(workorder.resolved_at)
        self.assertIsNotNone(workorder.closed_at)

    def test_save_update_fields_persists_generated_terminal_dates(self):
        self.workorder.status = WorkOrderStatus.CLOSED
        self.workorder.save(update_fields=["status"])

        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.status, WorkOrderStatus.CLOSED)
        self.assertIsNotNone(self.workorder.resolved_at)
        self.assertIsNotNone(self.workorder.closed_at)

    def test_transition_service_creates_audit_log(self):
        _transition_workorder_unchecked(
            workorder=self.workorder,
            user=self.technician,
            to_status=WorkOrderStatus.ACCEPTED,
        )
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.status, WorkOrderStatus.ACCEPTED)
        self.assertEqual(self.workorder.transitions.count(), 1)

    def test_create_workorder_service_notifies_visible_recipients_without_author(self):
        workorder = _create_workorder_unchecked(
            author=self.customer,
            title="Проверить кабель",
            description="Без чувствительных деталей в уведомлении.",
            department=self.department,
            priority="medium",
            assignee=self.technician,
            board=self.board,
        )

        recipients = set(
            NotificationRecipient.objects.filter(
                event__event_type="workorders.created",
                event__source_object_id=str(workorder.pk),
            ).values_list("user__username", flat=True)
        )

        self.assertIn(self.technician.username, recipients)
        self.assertIn(self.manager.username, recipients)
        self.assertNotIn(self.customer.username, recipients)
        self.assertNotIn(self.outsider.username, recipients)

    def test_transition_service_notifies_author_and_excludes_actor(self):
        _transition_workorder_unchecked(
            workorder=self.workorder,
            user=self.technician,
            to_status=WorkOrderStatus.ACCEPTED,
        )

        recipients = set(
            NotificationRecipient.objects.filter(
                event__event_type="workorders.status_changed",
                event__source_object_id=str(self.workorder.pk),
            ).values_list("user__username", flat=True)
        )

        self.assertIn(self.customer.username, recipients)
        self.assertIn(self.manager.username, recipients)
        self.assertNotIn(self.technician.username, recipients)

    def test_workorder_number_is_human_readable(self):
        self.assertEqual(self.workorder.number, str(self.workorder.pk))

    def test_transition_rights_can_come_from_settings_defined_role(self):
        dispatcher_rules = {
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
        with _override_contract_file(
            "LOCAL_BUSINESS_ROLE_RULES_FILE", "role_rules.json", dispatcher_rules
        ):
            dispatcher = User.objects.create_user(username="dispatcher", password="pass")
            dispatcher_group, _ = Group.objects.get_or_create(name="dispatcher")
            dispatcher.groups.add(dispatcher_group)

            self.assertTrue(can_view(dispatcher, self.workorder))
            self.assertTrue(can_transition(dispatcher, self.workorder, WorkOrderStatus.ACCEPTED))
            self.assertFalse(can_transition(dispatcher, self.workorder, WorkOrderStatus.IN_PROGRESS))

    def test_transition_matrix_can_come_from_workflow_config(self):
        workflow_rules = {
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
        with _override_contract_file(
            "LOCAL_BUSINESS_WORKFLOW_RULES_FILE", "workflow_rules.json", workflow_rules
        ):
            self.assertTrue(can_transition(self.technician, self.workorder, WorkOrderStatus.ACCEPTED))
            self.assertFalse(can_transition(self.technician, self.workorder, WorkOrderStatus.CANCELLED))

    def test_scoped_resource_selectors_cover_all_branch_none_and_inactive(self):
        foreign_department = Department.objects.create(name="Чужой филиал")
        foreign_device = MedicalDevice.objects.create(
            name="Чужой аппарат",
            serial_number="SN-FOREIGN-SCOPE",
            department=foreign_department,
        )
        WorkOrder.objects.create(
            title="Чужая заявка для scope",
            description="Не должна утечь в ветку.",
            department=foreign_department,
            author=self.outsider,
            assignee=self.manager,
            board=self.board,
            device=foreign_device,
        )
        none_group, _ = Group.objects.get_or_create(name="doctor")
        self.outsider.groups.add(none_group)

        self.assertIn(self.department.pk, visible_departments_queryset(self.manager).values_list("pk", flat=True))
        self.assertIn(foreign_department.pk, visible_departments_queryset(self.manager).values_list("pk", flat=True))
        self.assertNotIn(foreign_department.pk, visible_departments_queryset(self.customer).values_list("pk", flat=True))
        self.assertNotIn(foreign_device.pk, visible_devices_queryset(self.customer).values_list("pk", flat=True))
        self.assertFalse(visible_departments_queryset(self.outsider).exists())
        self.assertFalse(visible_devices_queryset(self.outsider).exists())

        self.manager.is_active = False
        self.manager.save(update_fields=["is_active"])
        self.assertFalse(visible_workorders_queryset(self.manager).exists())
        self.assertFalse(visible_departments_queryset(self.manager).exists())
        self.assertFalse(visible_devices_queryset(self.manager).exists())

    def test_relational_scope_uses_visible_workorders_but_creation_uses_own_branch(self):
        own_department = Department.objects.create(name="Свой филиал")
        own_device = MedicalDevice.objects.create(
            name="Свой аппарат",
            serial_number="SN-RELATIONAL-OWN",
            department=own_department,
        )
        foreign_department = Department.objects.create(name="Другой филиал")
        foreign_device = MedicalDevice.objects.create(
            name="Другой аппарат",
            serial_number="SN-RELATIONAL-FOREIGN",
            department=foreign_department,
        )
        relational = User.objects.create_user(
            username="relational-reader",
            password="pass",
            department=own_department,
        )
        relational_group, _ = Group.objects.get_or_create(name="relational-reader")
        relational.groups.add(relational_group)
        self.board.allowed_groups.add(relational_group)
        WorkOrder.objects.create(
            title="Связанная заявка",
            description="Видимая по назначению.",
            department=own_department,
            author=self.outsider,
            assignee=relational,
            board=self.board,
            device=own_device,
        )
        WorkOrder.objects.create(
            title="Несвязанная заявка",
            description="Назначена другому сотруднику.",
            department=foreign_department,
            author=self.outsider,
            assignee=self.manager,
            board=self.board,
            device=foreign_device,
        )
        role_rules = {
            "relational-reader": {
                **copy.deepcopy(get_contract("role_rules")["technician"]),
                "view_scope": "assigned",
            }
        }

        with _override_contract_file(
            "LOCAL_BUSINESS_ROLE_RULES_FILE", "role_rules.json", role_rules
        ):
            self.assertEqual(
                set(visible_departments_queryset(relational).values_list("pk", flat=True)),
                {own_department.pk},
            )
            self.assertEqual(
                set(visible_devices_queryset(relational).values_list("pk", flat=True)),
                {own_device.pk},
            )
            self.assertIn(
                own_department.pk,
                creation_departments_queryset(relational).values_list("pk", flat=True),
            )
            self.assertNotIn(
                foreign_department.pk,
                creation_departments_queryset(relational).values_list("pk", flat=True),
            )


@pytest.mark.integration
class WorkOrderViewPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.department = Department.objects.create(name="Стационар")
        cls.sub_department = Department.objects.create(name="ОРИТ", parent=cls.department)
        cls.device = MedicalDevice.objects.create(
            name="Монитор пациента",
            serial_number="SN-002",
            inventory_number="INV-002",
            department=cls.sub_department,
        )
        cls.customer = User.objects.create_user(
            username="customer2", password="pass", department=cls.sub_department
        )
        cls.technician = User.objects.create_user(username="tech2", password="pass")
        cls.manager = User.objects.create_user(username="manager2", password="pass")
        cls.outsider = User.objects.create_user(username="outsider2", password="pass")
        cls.default_viewer = User.objects.create_user(
            username="default-viewer2",
            password="pass",
            department=cls.sub_department,
        )

        tech_group, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)

        cls.technician.groups.add(tech_group)
        cls.manager.groups.add(manager_group)
        cls.customer.groups.add(customer_group)

        cls.board = Board.objects.create(title="Test Board 2", slug="test-board-2")
        cls.board.allowed_groups.add(manager_group, tech_group, customer_group)
        KanbanColumnConfig.objects.create(board=cls.board, code="new", title="Новые", position=10, statuses=["new"])
        KanbanColumnConfig.objects.create(board=cls.board, code="in_progress", title="В работе", position=20, statuses=["accepted", "in_progress", "on_hold"])
        KanbanColumnConfig.objects.create(board=cls.board, code="done", title="Выполнены", position=30, statuses=["resolved"])
        KanbanColumnConfig.objects.create(board=cls.board, code="archive", title="Архив", position=40, statuses=["closed", "cancelled"])
        cls.workorder = WorkOrder.objects.create(
            title="Заменить кабель",
            description="Поврежден кабель питания.",
            department=cls.sub_department,
            author=cls.customer,
            board=cls.board,
            assignee=cls.technician,
            device=cls.device,
        )

    def test_outsider_cannot_open_detail(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("workorders:detail", args=[self.workorder.pk]))
        self.assertEqual(response.status_code, 404)

    def test_outsider_cannot_open_board(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("workorders:board"))
        self.assertEqual(response.status_code, 403)

    def test_selector_board_argument_cannot_bypass_board_acl(self):
        private_group, _ = Group.objects.get_or_create(name="private-selector-board")
        private_board = Board.objects.create(
            title="Чужая доска для selector",
            slug="private-selector-board",
        )
        private_board.allowed_groups.add(private_group)
        foreign = WorkOrder.objects.create(
            title="Заявка на чужой доске",
            description="Не должна возвращаться с board=.",
            department=self.sub_department,
            author=self.customer,
            board=private_board,
            device=self.device,
        )

        self.assertTrue(
            visible_workorders_queryset(self.customer, board=self.board)
            .filter(pk=self.workorder.pk)
            .exists()
        )
        self.assertFalse(
            visible_workorders_queryset(self.customer, board=private_board)
            .filter(pk=foreign.pk)
            .exists()
        )

    def test_roleless_user_cannot_open_customer_board_or_write(self):
        self.client.force_login(self.default_viewer)

        response = self.client.get(reverse("workorders:board"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.client.get(reverse("workorders:create")).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("workorders:edit", args=[self.workorder.pk]),
                {
                    "title": "Недопустимое изменение",
                    "description": self.workorder.description,
                    "department": self.sub_department.pk,
                    "priority": self.workorder.priority,
                    "board": self.board.pk,
                },
            ).status_code,
            404,
        )

    def test_roleless_user_cannot_open_board_without_customer_group(self):
        private_group, _ = Group.objects.get_or_create(name="private-default-view")
        private_board = Board.objects.create(
            title="Закрытая доска",
            slug="private-default-view",
        )
        private_board.allowed_groups.add(private_group)
        self.client.force_login(self.default_viewer)

        response = self.client.get(
            reverse(
                "workorders:board_specific",
                kwargs={"board_slug": private_board.slug},
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_explicit_role_without_workorder_rights_cannot_open_board(self):
        doctor_group, _ = Group.objects.get_or_create(name="doctor")
        explicit_doctor = User.objects.create_user(
            username="explicit-doctor-board",
            password="pass",
            department=self.sub_department,
        )
        explicit_doctor.groups.add(doctor_group)
        self.client.force_login(explicit_doctor)

        response = self.client.get(reverse("workorders:board"))

        self.assertEqual(response.status_code, 403)

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
        self.assertContains(response, 'data-workorder-filter-form')
        self.assertContains(response, 'hx-push-url="true"')
        self.assertContains(response, 'data-column-code="')
        self.assertContains(response, 'data-workorders-sidebar-shell')
        self.assertContains(response, 'data-ai-sidebar-mode="filters"')
        self.assertContains(response, 'data-department-filter-tree')
        self.assertContains(response, 'form="workorder-filters"')
        self.assertContains(response, 'data-workorders-ai-launcher')
        self.assertContains(response, 'data-workorders-ai-panel')
        self.assertNotContains(response, 'name="view"')
        self.assertNotContains(response, 'id="workorders-tree"')

    def test_customer_visibility_is_limited_to_department_branch(self):
        sibling_department = Department.objects.create(
            name="Соседнее отделение", parent=self.department
        )
        sibling_device = MedicalDevice.objects.create(
            name="Чужой монитор",
            serial_number="SN-FOREIGN",
            department=sibling_department,
        )
        foreign = WorkOrder.objects.create(
            title="Заявка вне ветки",
            description="Даже authored заявка не должна быть видна вне ветки.",
            department=sibling_department,
            author=self.customer,
            board=self.board,
            device=sibling_device,
        )

        self.client.force_login(self.customer)
        response = self.client.get(reverse("workorders:board"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.workorder.title)
        self.assertNotContains(response, foreign.title)

        detail_response = self.client.get(reverse("workorders:detail", args=[foreign.pk]))
        self.assertEqual(detail_response.status_code, 404)

    def test_customer_in_unassigned_department_sees_empty_branch(self):
        customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)
        no_department_customer = User.objects.create_user(
            username="customer_without_department", password="pass"
        )
        no_department_customer.groups.add(customer_group)

        self.assertTrue(no_department_customer.requires_department_assignment)

        self.client.force_login(no_department_customer)
        response = self.client.get(reverse("workorders:board"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.workorder.title)

    def test_legacy_tree_view_redirects_to_canonical_board_url(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            f"{reverse('workorders:board')}?view=tree&status=new"
            "&status=accepted&q=sensor"
        )

        self.assertEqual(response.status_code, 302)
        location = urlsplit(response["Location"])
        self.assertEqual(location.path, reverse("workorders:board"))
        self.assertEqual(
            parse_qs(location.query),
            {"status": ["new", "accepted"], "q": ["sensor"]},
        )

    def test_unknown_legacy_view_is_safely_removed(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:board"),
            {"view": "unknown", "status": WorkOrderStatus.NEW},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{reverse('workorders:board')}?status={WorkOrderStatus.NEW}",
        )

    def test_canonical_redirect_preserves_all_repeated_board_filters(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:board"),
            {
                "view": "tree",
                "q": "кабель",
                "department": [
                    str(self.sub_department.pk),
                    str(self.department.pk),
                ],
                "status": [WorkOrderStatus.NEW, WorkOrderStatus.ACCEPTED],
                "assignee": [str(self.technician.pk), str(self.manager.pk)],
                "device": [str(self.device.pk), "999999"],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            parse_qs(urlsplit(response["Location"]).query),
            {
                "q": ["кабель"],
                "department": [str(self.department.pk)],
                "status": [WorkOrderStatus.NEW, WorkOrderStatus.ACCEPTED],
                "assignee": [str(self.technician.pk), str(self.manager.pk)],
                "device": [str(self.device.pk)],
            },
        )

    def test_board_filters_accept_multiple_values(self):
        accepted = WorkOrder.objects.create(
            title="Принятая заявка",
            description="Для проверки множественного фильтра.",
            department=self.sub_department,
            author=self.customer,
            board=self.board,
            status=WorkOrderStatus.ACCEPTED,
        )
        resolved = WorkOrder.objects.create(
            title="Выполненная заявка",
            description="Не должна попасть в выбранные статусы.",
            department=self.sub_department,
            author=self.customer,
            board=self.board,
            status=WorkOrderStatus.RESOLVED,
        )

        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:board"),
            {"status": [WorkOrderStatus.NEW, WorkOrderStatus.ACCEPTED]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.workorder.title)
        self.assertContains(response, accepted.title)
        self.assertNotContains(response, resolved.title)

    def test_backlog_board_is_created_for_portal_feedback(self):
        from importlib import import_module

        from django.apps import apps

        migration = import_module("apps.workorders.migrations.0016_create_backlog_board")
        migration.create_backlog_board(apps, schema_editor=None)
        board = Board.objects.get(slug="backlog")

        self.assertEqual(board.title, "Техподдержка")
        self.assertEqual(
            list(board.columns.order_by("position").values_list("code", flat=True)),
            ["new", "in_progress", "done", "archive"],
        )

    def test_legacy_htmx_view_renders_board_and_replaces_url(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:board"),
            {"view": "tree", "status": WorkOrderStatus.NEW},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="workorders-view",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_view"], "board")
        self.assertContains(response, 'id="workorders-view"')
        self.assertContains(response, 'id="board-columns"')
        self.assertNotContains(response, 'id="workorders-tree"')
        self.assertContains(response, self.workorder.title)
        self.assertEqual(
            response["HX-Replace-Url"],
            f"{reverse('workorders:board')}?status={WorkOrderStatus.NEW}",
        )

    def test_stored_tree_view_is_cleared_and_board_is_rendered(self):
        self.client.force_login(self.manager)
        session = self.client.session
        session["workorders:view_mode"] = "tree"
        session.save()

        response = self.client.get(reverse("workorders:board"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_view"], "board")
        self.assertNotIn("workorders:view_mode", self.client.session)

    def test_htmx_replaces_url_with_normalized_department_roots(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:board"),
            {
                "department": [
                    str(self.sub_department.pk),
                    str(self.department.pk),
                ]
            },
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="workorders-view",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["HX-Replace-Url"],
            f"{reverse('workorders:board')}?department={self.department.pk}",
        )
        self.assertEqual(
            response.context["department_filter"]["selected_ids"],
            (self.department.pk,),
        )

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
        self.assertContains(response, 'data-autocomplete-kind="department"')
        self.assertContains(response, 'data-autocomplete-kind="device"')
        self.assertNotContains(response, 'name="title"')
        self.assertNotContains(response, 'name="assignee"')
        self.assertEqual(
            response.context["form"].initial["department"],
            self.customer.department_id,
        )

    def test_legacy_tree_create_prefills_fields_but_returns_to_board(self):
        self.client.force_login(self.customer)
        response = self.client.get(
            (
                f"{reverse('workorders:create')}?board={self.board.pk}"
                f"&department={self.sub_department.pk}&device={self.device.pk}"
                "&return_view=tree"
            ),
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="detail-panel-content",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["return_view"], "board")
        self.assertEqual(
            str(response.context["form"].initial["department"]),
            str(self.sub_department.pk),
        )
        self.assertEqual(str(response.context["form"].initial["device"]), str(self.device.pk))
        self.assertEqual(
            response.context["form"].initial["description"],
            self.device.name,
        )
        self.assertContains(response, self.device.inventory_number)
        self.assertNotContains(response, self.device.serial_number)

    def test_create_prefill_uses_accessible_device_department_as_source_of_truth(self):
        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("workorders:create"),
            {
                "board": self.board.pk,
                "department": self.department.pk,
                "device": self.device.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["device"], self.device.pk)
        self.assertEqual(
            response.context["form"].initial["department"],
            self.device.department_id,
        )

    def test_create_prefill_ignores_invalid_inaccessible_and_archived_devices(self):
        sibling_department = Department.objects.create(
            name="Неврология",
            parent=self.department,
        )
        inaccessible_device = MedicalDevice.objects.create(
            name="Чужой аппарат",
            serial_number="SN-PREFILL-FOREIGN",
            department=sibling_department,
        )
        archived_device = MedicalDevice.objects.create(
            name="Архивный аппарат",
            serial_number="SN-PREFILL-ARCHIVE",
            department=self.sub_department,
        )
        archived_device.archive()
        self.client.force_login(self.customer)

        for device_value in (
            "not-an-id",
            inaccessible_device.pk,
            archived_device.pk,
        ):
            with self.subTest(device=device_value):
                response = self.client.get(
                    reverse("workorders:create"),
                    {"board": self.board.pk, "device": device_value},
                )
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.context["form"].initial.get("device"))
                self.assertEqual(
                    response.context["form"].initial.get("department"),
                    self.customer.department_id,
                )

    def test_create_autocomplete_searches_device_by_name_inventory_and_serial(self):
        self.client.force_login(self.customer)

        for query in (self.device.name, self.device.inventory_number, self.device.serial_number):
            with self.subTest(query=query):
                response = self.client.get(
                    reverse("workorders:create_device_options"),
                    {"q": query},
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])
                result = response.json()["results"][0]
                self.assertEqual(result["id"], self.device.pk)
                self.assertIn(self.device.inventory_number, result["label"])
                self.assertNotIn(self.device.serial_number, result["label"])
                self.assertEqual(result["department_id"], self.sub_department.pk)

    def test_create_autocomplete_limits_departments_to_visible_branch(self):
        hidden_department = Department.objects.create(
            name="Скрытая лаборатория",
            parent=self.department,
        )
        self.client.force_login(self.customer)

        visible_response = self.client.get(
            reverse("workorders:create_department_options"),
            {"q": self.sub_department.name},
        )
        hidden_response = self.client.get(
            reverse("workorders:create_department_options"),
            {"q": hidden_department.name},
        )

        self.assertEqual(visible_response.status_code, 200)
        self.assertEqual(
            visible_response.json()["results"][0]["id"],
            self.sub_department.pk,
        )
        self.assertEqual(hidden_response.json()["results"], [])

    def test_create_autocomplete_excludes_inaccessible_and_archived_devices(self):
        hidden_department = Department.objects.create(
            name="Скрытое отделение автопоиска",
            parent=self.department,
        )
        MedicalDevice.objects.create(
            name="Недоступное изделие автопоиска",
            inventory_number="AUTO-HIDDEN",
            department=hidden_department,
        )
        archived_device = MedicalDevice.objects.create(
            name="Архивное изделие автопоиска",
            inventory_number="AUTO-ARCHIVED",
            department=self.sub_department,
        )
        archived_device.archive()
        self.client.force_login(self.customer)

        hidden_response = self.client.get(
            reverse("workorders:create_device_options"),
            {"q": "AUTO-HIDDEN"},
        )
        archived_response = self.client.get(
            reverse("workorders:create_device_options"),
            {"q": "AUTO-ARCHIVED"},
        )

        self.assertEqual(hidden_response.json()["results"], [])
        self.assertEqual(archived_response.json()["results"], [])

    def test_create_autocomplete_requires_create_permission(self):
        self.client.force_login(self.outsider)

        response = self.client.get(reverse("workorders:create_device_options"))

        self.assertEqual(response.status_code, 403)

    def test_edit_preserves_existing_archived_device(self):
        archived_device = MedicalDevice.objects.create(
            name="Архивный монитор",
            serial_number="SN-EDIT-ARCHIVE",
            department=self.sub_department,
        )
        archived_device.archive()
        self.workorder.device = archived_device
        self.workorder.save(update_fields=["device", "updated_at"])
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("workorders:edit", args=[self.workorder.pk]),
            {
                "board": self.board.pk,
                "title": "Заявка с архивным изделием",
                "description": self.workorder.description,
                "department": self.sub_department.pk,
                "priority": self.workorder.priority,
                "device": archived_device.pk,
                "assignee": self.technician.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.workorder.refresh_from_db()
        self.assertEqual(self.workorder.device, archived_device)
        self.assertEqual(self.workorder.title, "Заявка с архивным изделием")

    def test_customer_create_form_rejects_foreign_department_branch(self):
        sibling_department = Department.objects.create(
            name="Неврология", parent=self.department
        )
        sibling_device = MedicalDevice.objects.create(
            name="Чужой аппарат",
            serial_number="SN-FORM-FOREIGN",
            department=sibling_department,
        )

        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("workorders:create"),
            {
                "title": "Чужая ветка",
                "description": "Попытка создать вне своей ветки.",
                "department": sibling_department.pk,
                "priority": "medium",
                "device": sibling_device.pk,
                "assignee": "",
                "board": self.board.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            WorkOrder.objects.filter(description="Попытка создать вне своей ветки.").exists()
        )
        self.assertIn("department", response.context["form"].errors)

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

    def test_htmx_comment_render_rechecks_scope_after_command(self):
        from unittest.mock import patch

        self.client.force_login(self.customer)
        with patch(
            "apps.workorders.views.add_workorder_comment_command",
            return_value=SimpleNamespace(workorder=self.workorder),
        ), patch(
            "apps.workorders.views._fresh_render_actor_and_workorder",
            side_effect=PermissionDenied,
        ):
            response = self.client.post(
                reverse("workorders:comment", args=[self.workorder.pk]),
                {"body": "Комментарий"},
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 403)

    def test_htmx_attachment_render_rechecks_scope_after_command(self):
        from unittest.mock import patch

        self.client.force_login(self.customer)
        upload = SimpleUploadedFile("note.txt", b"note", content_type="text/plain")
        with patch(
            "apps.workorders.views.add_workorder_attachment_command",
            return_value=SimpleNamespace(workorder=self.workorder),
        ), patch(
            "apps.workorders.views._fresh_render_actor_and_workorder",
            side_effect=PermissionDenied,
        ):
            response = self.client.post(
                reverse("workorders:attachment", args=[self.workorder.pk]),
                {"file": upload},
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 403)

    def test_board_move_render_rechecks_actor_and_board_context(self):
        from unittest.mock import patch

        column = self.board.columns.get(code="in_progress")
        self.client.force_login(self.technician)
        with patch(
            "apps.workorders.views.move_workorder_command",
            return_value=(self.workorder, self.workorder.status, column),
        ), patch(
            "apps.workorders.views._fresh_render_actor_and_workorder",
            side_effect=PermissionDenied,
        ):
            response = self.client.post(
                reverse("workorders:board_move", args=[self.workorder.pk]),
                {"column": "in_progress"},
                HTTP_HX_REQUEST="true",
                HTTP_HX_TARGET="board-columns",
            )
        self.assertEqual(response.status_code, 403)

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
        self.assertEqual(created.title, "")

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
        self.assertEqual(created.title, "")
        self.assertEqual(created.board, self.board)
        self.assertEqual(created.author, self.customer)

    def test_legacy_tree_return_view_is_ignored_after_create(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse("workorders:create"),
            {
                "title": "Заявка из дерева",
                "description": "Создана через правую панель дерева.",
                "department": self.sub_department.pk,
                "priority": "medium",
                "device": self.device.pk,
                "assignee": "",
                "board": self.board.pk,
                "return_view": "tree",
            },
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="detail-panel-content",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response["HX-Redirect"],
            reverse(
                "workorders:board_specific",
                kwargs={"board_slug": self.board.slug},
            ),
        )
        created = WorkOrder.objects.exclude(pk=self.workorder.pk).get()
        self.assertEqual(created.title, "")
        self.assertEqual(created.device, self.device)

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
        self.assertEqual(created.title, "")

    def test_manager_cannot_assign_executor_during_creation(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("workorders:create"),
            {
                "description": "Исполнитель определяется после регистрации заявки.",
                "department": self.sub_department.pk,
                "priority": "medium",
                "device": self.device.pk,
                "assignee": self.technician.pk,
                "board": self.board.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        created = WorkOrder.objects.exclude(pk=self.workorder.pk).get()
        self.assertEqual(created.title, "")
        self.assertIsNone(created.assignee)

    def test_create_rejects_device_from_another_department(self):
        another_department = Department.objects.create(name="Диагностика")
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("workorders:create"),
            {
                "description": "Несогласованные данные формы.",
                "department": another_department.pk,
                "priority": "medium",
                "device": self.device.pk,
                "board": self.board.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("department", response.context["form"].errors)
        self.assertFalse(
            WorkOrder.objects.filter(description="Несогласованные данные формы.").exists()
        )

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
        _confirm_closure_unchecked(workorder=self.workorder, user=self.customer)
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
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:board"),
            {"department": self.department.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.workorder.title)

    def test_department_filter_normalizes_ancestor_and_descendant(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:board"),
            {
                "department": [
                    str(self.sub_department.pk),
                    str(self.department.pk),
                ]
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain,
            [
                (
                    f"{reverse('workorders:board')}?department={self.department.pk}",
                    302,
                )
            ],
        )
        self.assertEqual(
            response.context["department_filter"]["selected_ids"],
            (self.department.pk,),
        )
        self.assertEqual(
            response.context["filters"]["department_values"],
            [str(self.department.pk)],
        )
        self.assertContains(response, self.workorder.title)

    def test_customer_department_filter_ignores_inaccessible_and_invalid_ids(self):
        sibling_department = Department.objects.create(
            name="Недоступное отделение",
            parent=self.department,
        )
        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("workorders:board"),
            {
                "department": [
                    str(sibling_department.pk),
                    "not-an-id",
                    "-1",
                ]
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain,
            [(reverse("workorders:board"), 302)],
        )
        self.assertEqual(response.context["filters"]["department_values"], [])
        self.assertContains(response, self.workorder.title)
        nodes = response.context["department_filter"]["nodes"]
        department_nodes = [node for node in nodes if node["kind"] == "department"]
        self.assertEqual(
            [node["department_id"] for node in department_nodes],
            [self.sub_department.pk],
        )
        self.assertIsNone(department_nodes[0]["parent_id"])

    def test_department_filter_keeps_two_independent_visible_branches(self):
        other_department = Department.objects.create(name="Поликлиника")
        other_workorder = WorkOrder.objects.create(
            title="Проверить регистратуру",
            description="Заявка другой независимой ветви.",
            department=other_department,
            author=self.manager,
            board=self.board,
        )
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("workorders:board"),
            {
                "department": [
                    str(self.sub_department.pk),
                    str(other_department.pk),
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["department_filter"]["selected_ids"],
            (self.sub_department.pk, other_department.pk),
        )
        self.assertContains(response, self.workorder.title)
        self.assertContains(response, other_workorder.title)

    def test_tree_contains_active_device_leaves_and_excludes_archived_devices(self):
        archived_device = MedicalDevice.objects.create(
            name="Старый монитор",
            serial_number="SN-TREE-ARCHIVE",
            department=self.sub_department,
        )
        archived_device.archive()
        self.client.force_login(self.manager)

        response = self.client.get(reverse("workorders:board"))

        self.assertEqual(response.status_code, 200)
        nodes = response.context["department_filter"]["nodes"]
        device_nodes = [node for node in nodes if node["kind"] == "device"]
        self.assertIn(self.device.pk, [node["device_id"] for node in device_nodes])
        self.assertNotIn(
            archived_device.pk,
            [node["device_id"] for node in device_nodes],
        )
        active_node = next(
            node for node in device_nodes if node["device_id"] == self.device.pk
        )
        self.assertEqual(
            active_node["parent_key"],
            f"department:{self.sub_department.pk}",
        )
        self.assertFalse(active_node["has_children"])

    def test_tree_filter_combines_department_branches_and_devices_with_or(self):
        other_department = Department.objects.create(name="Поликлиника для OR")
        selected_device = MedicalDevice.objects.create(
            name="Выбранный аппарат",
            serial_number="SN-OR-SELECTED",
            department=other_department,
        )
        other_device = MedicalDevice.objects.create(
            name="Другой аппарат",
            serial_number="SN-OR-OTHER",
            department=other_department,
        )
        selected_device_workorder = WorkOrder.objects.create(
            title="Заявка выбранного аппарата",
            description="Попадает по выбранному изделию.",
            department=other_department,
            author=self.manager,
            board=self.board,
            device=selected_device,
        )
        excluded_workorder = WorkOrder.objects.create(
            title="Заявка другого аппарата",
            description="Не входит ни в одну выбранную ветвь.",
            department=other_department,
            author=self.manager,
            board=self.board,
            device=other_device,
        )
        self.client.force_login(self.manager)

        response = self.client.get(
            reverse("workorders:board"),
            {
                "department": self.sub_department.pk,
                "device": selected_device.pk,
                "status": WorkOrderStatus.NEW,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.workorder.title)
        self.assertContains(response, selected_device_workorder.title)
        self.assertNotContains(response, excluded_workorder.title)
        tree_context = response.context["department_filter"]
        self.assertEqual(
            tree_context["selected_department_ids"],
            (self.sub_department.pk,),
        )
        self.assertEqual(
            tree_context["selected_device_ids"],
            (selected_device.pk,),
        )
        self.assertEqual(tree_context["selected_count"], 2)
        self.assertTrue(tree_context["can_create_workorder"])

    def test_tree_device_filter_is_normalized_inside_customer_access(self):
        sibling_department = Department.objects.create(
            name="Недоступная ветка изделий",
            parent=self.department,
        )
        inaccessible_device = MedicalDevice.objects.create(
            name="Недоступное изделие",
            serial_number="SN-TREE-FOREIGN",
            department=sibling_department,
        )
        archived_device = MedicalDevice.objects.create(
            name="Архивное изделие",
            serial_number="SN-TREE-ARCHIVED",
            department=self.sub_department,
        )
        archived_device.archive()
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse("workorders:board"),
            {
                "device": [
                    str(self.device.pk),
                    str(inaccessible_device.pk),
                    str(archived_device.pk),
                    "bad",
                ]
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain,
            [
                (
                    f"{reverse('workorders:board')}?device={self.device.pk}",
                    302,
                )
            ],
        )
        self.assertEqual(
            response.context["department_filter"]["selected_device_ids"],
            (self.device.pk,),
        )

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

    def test_board_search_matches_device_inventory_and_serial_numbers(self):
        self.client.force_login(self.manager)

        for query in (self.device.inventory_number, self.device.serial_number):
            with self.subTest(query=query):
                response = self.client.get(reverse("workorders:board"), {"q": query})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.workorder.title)

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


@pytest.mark.integration
class StepperContextTests(TestCase):
    """Tests for _stepper_context and status_section template variables."""

    @classmethod
    def setUpTestData(cls):
        cls.department = Department.objects.create(name="Рентген")
        cls.device = MedicalDevice.objects.create(
            name="Рентген-аппарат",
            serial_number="SN-X01",
            department=cls.department,
        )
        cls.customer = User.objects.create_user(
            username="cust_stepper", password="pass", department=cls.department
        )
        cls.technician = User.objects.create_user(username="tech_stepper", password="pass")
        cls.manager = User.objects.create_user(username="mgr_stepper", password="pass")

        tech_group, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
        customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)

        cls.technician.groups.add(tech_group)
        cls.manager.groups.add(manager_group)
        cls.customer.groups.add(customer_group)

        cls.board = Board.objects.create(title="Stepper Board", slug="stepper-board")
        cls.board.allowed_groups.add(manager_group, tech_group, customer_group)
        cls.workorder = WorkOrder.objects.create(
            title="Stepper test",
            description="Testing stepper context.",
            department=cls.department,
            author=cls.customer,
            board=cls.board,
            assignee=cls.technician,
            device=cls.device,
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


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
@pytest.mark.integration
class WorkOrderAttachmentServingTests(TestCase):
    """Авторизованная выдача файлов вложений через view.

    MEDIA_ROOT подменяется на временный каталог, чтобы записанные в тесте файлы
    не попадали в data/media/. Раздача идёт через тот же URL /media/workorders/,
    что и ``attachment.file.url`` в шаблонах, но за ним теперь стоит view с
    login_required + can_view вместо снятого static(MEDIA_URL, ...).
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.department = Department.objects.create(name="Лаборатория")
        self.device = MedicalDevice.objects.create(
            name="Анализатор",
            serial_number="SN-ATT-01",
            department=self.department,
        )
        self.customer = User.objects.create_user(
            username="att_customer", password="pass", department=self.department
        )
        self.technician = User.objects.create_user(username="att_tech", password="pass")
        self.outsider = User.objects.create_user(username="att_outsider", password="pass")

        tech_group, _ = Group.objects.get_or_create(name=ROLE_TECHNICIAN)
        customer_group, _ = Group.objects.get_or_create(name=ROLE_CUSTOMER)
        self.technician.groups.add(tech_group)
        self.customer.groups.add(customer_group)

        self.board = Board.objects.create(title="Attach Board", slug="attach-board")
        self.board.allowed_groups.add(tech_group, customer_group)
        self.workorder = WorkOrder.objects.create(
            title="Заявка с вложением",
            description="Есть прикреплённый файл.",
            department=self.department,
            author=self.customer,
            board=self.board,
            assignee=self.technician,
            device=self.device,
        )
        self.attachment = WorkOrderAttachment.objects.create(
            workorder=self.workorder,
            uploaded_by=self.customer,
            file=SimpleUploadedFile(
                "photo.jpg", b"binary-image-bytes", content_type="image/jpeg"
            ),
            content_type="image/jpeg",
        )
        self.file_url = self.attachment.file.url

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.file_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_outsider_without_access_gets_404(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self.file_url)
        self.assertEqual(response.status_code, 404)

    def test_user_with_access_receives_file_with_content_type(self):
        self.client.force_login(self.customer)
        response = self.client.get(self.file_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(b"".join(response.streaming_content), b"binary-image-bytes")

    def test_path_traversal_attempt_returns_404(self):
        # Секрет за пределами MEDIA_ROOT; пытаемся достать его через ../../.
        secret = Path(settings.MEDIA_ROOT).resolve().parent / "wo_secret.txt"
        secret.write_bytes(b"top-secret")
        self.addCleanup(secret.unlink, missing_ok=True)

        self.client.force_login(self.customer)
        response = self.client.get("/media/workorders/../../wo_secret.txt")
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "top-secret", status_code=404)

    def test_url_encoded_traversal_attempt_returns_404(self):
        # URL-кодированный обход (%2e%2e%2f == ../): WSGI декодирует его в
        # PATH_INFO до Django, поэтому guard обязан отбить и такой вариант.
        secret = Path(settings.MEDIA_ROOT).resolve().parent / "wo_secret_enc.txt"
        secret.write_bytes(b"top-secret")
        self.addCleanup(secret.unlink, missing_ok=True)

        self.client.force_login(self.customer)
        for url in (
            "/media/workorders/%2e%2e%2f%2e%2e%2fwo_secret_enc.txt",
            "/media/workorders/..%2f..%2fwo_secret_enc.txt",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404, url)
            self.assertNotContains(response, "top-secret", status_code=404)

    def test_null_byte_in_path_returns_404_not_500(self):
        # Null-байт ломает Path.resolve() (ValueError); без явного отсечения это
        # был бы неперехваченный HTTP 500. Ожидаем аккуратный 404.
        self.client.force_login(self.customer)
        response = self.client.get("/media/workorders/photo\x00.jpg")
        self.assertEqual(response.status_code, 404)

    def test_missing_file_on_disk_returns_404(self):
        # Запись о вложении есть, а файла на диске нет — не 500, а 404.
        Path(self.attachment.file.path).unlink()
        self.client.force_login(self.customer)
        response = self.client.get(self.file_url)
        self.assertEqual(response.status_code, 404)


@pytest.mark.integration
class CapabilityRegistryTests(TestCase):
    """capability_flags()/superuser_rules() читают справочник "$capabilities"
    контракта ролей (ADR-0034). Тесты работают на изолированной копии
    contracts/role_rules.json, чтобы не зависеть от состояния data/contracts/."""

    def setUp(self):
        self.base_role_rules = json_utils.load_json_file("contracts/role_rules.json")

    def test_capability_flags_returns_nonempty_triples_with_expected_keys(self):
        with _override_contract_file(
            "LOCAL_BUSINESS_ROLE_RULES_FILE", "role_rules.json", self.base_role_rules
        ):
            flags = capability_flags()

        self.assertTrue(flags)
        for key, label, _description in flags:
            self.assertTrue(key)
            self.assertTrue(label)

        keys = {key for key, _label, _description in flags}
        self.assertIn("create_waiting_list", keys)
        self.assertNotIn("view_waiting_list", keys)
        self.assertIn("memory_organization_write", keys)

    def test_every_capability_has_ui_section_and_risk_metadata(self):
        capabilities = self.base_role_rules["$capabilities"]

        self.assertTrue(capabilities)
        for key, metadata in capabilities.items():
            self.assertIn(
                metadata.get("section"),
                {
                    "workorders",
                    "organization",
                    "ai_memory",
                    "personal_data",
                    "waiting_list",
                    "warehouse",
                },
                f"{key}: неизвестный section",
            )
            self.assertIn(
                metadata.get("risk"),
                {"normal", "elevated", "critical"},
                f"{key}: неизвестный risk",
            )

    def test_superuser_rules_grant_every_capability_flag_and_full_scope(self):
        with _override_contract_file(
            "LOCAL_BUSINESS_ROLE_RULES_FILE", "role_rules.json", self.base_role_rules
        ):
            flags = capability_flags()
            rules = superuser_rules()

        # Регресс-тест дрейфа: любое новое булево право из контракта обязано
        # автоматически попадать в права суперпользователя.
        for key, _label, _description in flags:
            self.assertTrue(rules.get(key), f"superuser_rules() не содержит право '{key}'")

        self.assertEqual(rules["view_scope"], "all")
        self.assertEqual(rules["transition_targets"], "*")
        self.assertEqual(rules["waiting_list_view_scope"], "all")
        self.assertEqual(rules["waiting_list_edit_scope"], "all")
        self.assertEqual(rules["waiting_list_edit_statuses"], "*")
        self.assertEqual(rules["waiting_list_transition_scope"], "all")
        self.assertEqual(rules["waiting_list_transition_from_statuses"], "*")
        self.assertEqual(rules["waiting_list_transition_targets"], "*")

    def test_legacy_superuser_and_roleless_rules_remain_fail_closed(self):
        legacy_rules = {
            "legacy": {
                "view_waiting_list": True,
                "create_waiting_list": True,
            }
        }
        root = User.objects.create_superuser(username="legacy-rules-root")
        roleless = User.objects.create_user(username="active-roleless")
        inactive = User.objects.create_user(username="inactive-roleless")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])

        self.assertEqual(active_role_rules(root, rules_payload=legacy_rules)[0]["name"], "superuser")
        self.assertTrue(active_role_rules(root, rules_payload=legacy_rules)[0]["view_waiting_list"])
        self.assertEqual(active_role_rules(roleless, rules_payload=legacy_rules), [])
        self.assertEqual(active_role_rules(inactive, rules_payload=legacy_rules), [])

    def test_inactive_superuser_has_no_capabilities(self):
        inactive_root = User.objects.create_superuser(username="inactive-policy-root")
        inactive_root.is_active = False
        inactive_root.save(update_fields=["is_active"])

        with _override_contract_file(
            "LOCAL_BUSINESS_ROLE_RULES_FILE", "role_rules.json", self.base_role_rules
        ):
            self.assertFalse(has_role_capability(inactive_root, "manage_roles"))

    def test_every_contract_role_has_display_name_and_description(self):
        with _override_contract_file(
            "LOCAL_BUSINESS_ROLE_RULES_FILE", "role_rules.json", self.base_role_rules
        ):
            role_rules = get_contract("role_rules")

        roles_checked = 0
        for role, config in role_rules.items():
            if role.startswith("$"):
                continue
            roles_checked += 1
            display_name = config.get("display_name")
            description = config.get("description")
            self.assertIsInstance(display_name, str)
            self.assertTrue(display_name.strip(), f"{role}: пустой display_name")
            self.assertIsInstance(description, str)
            self.assertTrue(description.strip(), f"{role}: пустой description")

        self.assertGreater(roles_checked, 0)

    def test_role_contract_rejects_string_flag_and_unknown_capability(self):
        string_flag = copy.deepcopy(self.base_role_rules)
        string_flag["customer"]["create_workorder"] = "false"
        with self.assertRaisesMessage(ValidationError, "логическим"):
            validate_role_rules_payload(string_flag)

        unknown_capability = copy.deepcopy(self.base_role_rules)
        unknown_capability["customer"]["unregistered_access"] = True
        with self.assertRaisesMessage(ValidationError, "неизвестные права"):
            validate_role_rules_payload(unknown_capability)

    def test_role_contract_validates_default_new_user_role(self):
        valid = copy.deepcopy(self.base_role_rules)
        valid["$defaults"] = {"new_user_role": "customer"}
        validate_role_rules_payload(valid)

        invalid = copy.deepcopy(self.base_role_rules)
        invalid["$defaults"] = {"new_user_role": "missing-role"}
        with self.assertRaisesMessage(ValidationError, "$defaults.new_user_role"):
            validate_role_rules_payload(invalid)

    def test_waiting_list_capabilities_have_separate_sources_and_doctor_defaults(self):
        from .contracts import capability_values

        metadata = self.base_role_rules["$capabilities"]
        for code in (
            "view_scope",
            "transition_targets",
            "waiting_list_view_scope",
            "waiting_list_edit_statuses",
            "waiting_list_transition_targets",
        ):
            self.assertIn("values_source", metadata[code])
        self.assertEqual(
            set(capability_values("waiting_list_scopes")),
            {"none", "authored", "all"},
        )
        self.assertEqual(
            set(capability_values("waiting_list_statuses")),
            {"waiting", "scheduled", "confirmed", "cancelled", "*"},
        )
        self.assertEqual(
            self.base_role_rules["doctor"]["waiting_list_edit_statuses"],
            ["waiting", "scheduled"],
        )
        self.assertEqual(
            self.base_role_rules["doctor"]["waiting_list_transition_from_statuses"],
            ["waiting", "scheduled", "confirmed"],
        )
        self.assertEqual(
            self.base_role_rules["doctor"]["waiting_list_transition_targets"],
            ["waiting", "scheduled", "confirmed", "cancelled"],
        )
        for role in ("customer", "technician", "manager", "admin"):
            self.assertEqual(self.base_role_rules[role]["waiting_list_edit_scope"], "none")
            self.assertEqual(self.base_role_rules[role]["waiting_list_edit_statuses"], [])
            self.assertEqual(self.base_role_rules[role]["waiting_list_transition_scope"], "none")
            self.assertEqual(self.base_role_rules[role]["waiting_list_transition_targets"], [])

    def test_waiting_list_related_invariants_and_values_source_fail_closed(self):
        invalid_edit = copy.deepcopy(self.base_role_rules)
        invalid_edit["doctor"]["waiting_list_edit_scope"] = "none"
        with self.assertRaisesMessage(ValidationError, "требует пустого списка"):
            validate_role_rules_payload(invalid_edit)

        invalid_transition = copy.deepcopy(self.base_role_rules)
        invalid_transition["doctor"]["waiting_list_transition_scope"] = "none"
        with self.assertRaisesMessage(ValidationError, "отключённый переход"):
            validate_role_rules_payload(invalid_transition)

        unknown_source = copy.deepcopy(self.base_role_rules)
        unknown_source["$capabilities"]["waiting_list_view_scope"]["values_source"] = "future"
        with self.assertRaisesMessage(ValidationError, "известное поле values_source"):
            validate_role_rules_payload(unknown_source)

        missing_source = copy.deepcopy(self.base_role_rules)
        missing_source["$capabilities"]["waiting_list_view_scope"].pop("values_source")
        with self.assertRaisesMessage(ValidationError, "известное поле values_source"):
            validate_role_rules_payload(missing_source)

    def test_legacy_role_payload_without_waiting_capabilities_remains_compatible(self):
        legacy = copy.deepcopy(self.base_role_rules)
        waiting_codes = (
            "waiting_list_view_scope",
            "waiting_list_edit_scope",
            "waiting_list_edit_statuses",
            "waiting_list_transition_scope",
            "waiting_list_transition_from_statuses",
            "waiting_list_transition_targets",
        )
        role_names = [key for key in legacy if not key.startswith("$")]
        for code in waiting_codes:
            legacy["$capabilities"].pop(code)
            for role in role_names:
                legacy[role].pop(code)
        legacy["$capabilities"]["view_waiting_list"] = {
            "type": "flag",
            "section": "personal_data",
            "risk": "critical",
            "label": "Просмотр листа ожидания",
            "description": "Совместимый старый флаг просмотра листа ожидания.",
        }
        for role in role_names:
            legacy[role]["view_waiting_list"] = role == "doctor"
        for code in (
            "view_scope",
            "edit_scope",
            "comment_scope",
            "upload_attachment_scope",
            "confirm_closure_scope",
            "rate_scope",
            "transition_scope",
            "transition_targets",
        ):
            legacy["$capabilities"][code].pop("values_source", None)

        validate_role_rules_payload(legacy)

    def test_legacy_administration_metadata_is_parseable_but_inert(self):
        legacy = copy.deepcopy(self.base_role_rules)
        legacy["$administration"] = {
            "role_definition_editor_roles": ["missing"],
            "role_assignment_allowlist": {"missing": ["admin"]},
        }

        validate_role_rules_payload(legacy)

    def test_missing_assignment_allowlist_is_backward_compatible_and_fail_closed(self):
        legacy = copy.deepcopy(self.base_role_rules)
        legacy.pop("$administration", None)

        validate_role_rules_payload(legacy)

    def test_explicit_protected_flag_must_be_boolean(self):
        invalid = copy.deepcopy(self.base_role_rules)
        invalid["customer"]["protected"] = "false"
        with self.assertRaisesMessage(ValidationError, "логическим"):
            validate_role_rules_payload(invalid)
    can_comment,
    can_create,
    can_edit,


@pytest.mark.unit
class ExplicitViewerPolicyPhaseTests(TestCase):
    def test_runtime_viewer_presence_disables_legacy_fallback(self):
        payload = copy.deepcopy(get_contract("role_rules"))
        default_viewer = json_utils.load_json_file(
            Path(settings.BASE_DIR) / "contracts" / "role_rules.json"
        )["viewer"]
        supported_fields = {
            "display_name",
            "description",
            "protected",
            *payload["$capabilities"],
        }
        payload["viewer"] = {
            key: copy.deepcopy(value)
            for key, value in default_viewer.items()
            if key in supported_fields
        }
        user = User.objects.create_user(username="runtime-viewer-phase")
        with _override_contract_file("LOCAL_BUSINESS_ROLE_RULES_FILE", "role_rules.json", payload):
            self.assertFalse(default_board_access_applies(user))
            self.assertEqual(active_role_rules(user), [])
