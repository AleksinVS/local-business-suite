"""Проверки единой actor-aware границы изменения заявок."""

import json
import tempfile
from unittest.mock import patch
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings

from apps.core.contract_store import _reset_for_tests, get_contract
from apps.core.models import Department

from .models import Board, WorkOrder, WorkOrderTransitionLog
from .selectors import resolve_active_actor, visible_boards_queryset, visible_workorders_queryset
from .services import (
    clone_board,
    create_workorder_command,
    transition_workorder_command,
    update_workorder_command,
)


User = get_user_model()


@pytest.mark.integration
class WorkOrderActorCommandTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Команды заявок")
        self.actor = User.objects.create_user(
            username="command-actor",
            password="pass",
            department=self.department,
        )
        self.group = Group.objects.create(name="command-role")
        self.actor.groups.add(self.group)
        self.board = Board.objects.create(title="Командная доска", slug="command-board")
        self.board.allowed_groups.add(self.group)
        payload = json.loads(json.dumps(get_contract("role_rules")))
        payload["command-role"] = {
            **payload["customer"],
            "view_scope": "department_branch",
            "create_workorder": True,
            "edit_scope": "all",
            "manage_assignments": True,
            "manage_roles": True,
            "transition_scope": "department_branch",
            "transition_targets": ["cancelled"],
        }
        self.tmpdir = tempfile.TemporaryDirectory()
        self.rules_path = Path(self.tmpdir.name) / "role_rules.json"
        self.rules_path.write_text(json.dumps(payload), encoding="utf-8")
        self.settings_context = override_settings(
            LOCAL_BUSINESS_ROLE_RULES_FILE=self.rules_path
        )
        self.settings_context.enable()
        _reset_for_tests()

    def tearDown(self):
        _reset_for_tests()
        self.settings_context.disable()
        self.tmpdir.cleanup()

    def test_transition_rechecks_fresh_actor_and_keeps_log_consistent(self):
        workorder = create_workorder_command(
            actor=self.actor,
            payload={
                "board": self.board,
                "department": self.department,
                "title": "Проверка команды",
                "description": "Описание",
            },
        )
        self.actor.groups.remove(self.group)
        with self.assertRaises(PermissionDenied):
            transition_workorder_command(
                actor=self.actor,
                workorder_id=workorder.pk,
                target_status="cancelled",
            )
        workorder.refresh_from_db()
        self.assertEqual(workorder.status, "new")
        self.assertFalse(WorkOrderTransitionLog.objects.filter(workorder=workorder).exists())

    def test_cancel_transition_writes_object_and_transition_log(self):
        workorder = create_workorder_command(
            actor=self.actor,
            payload={
                "board": self.board,
                "department": self.department,
                "title": "Отмена",
                "description": "Описание",
            },
        )
        transition_workorder_command(
            actor=self.actor,
            workorder_id=workorder.pk,
            target_status="cancelled",
        )
        workorder.refresh_from_db()
        log = WorkOrderTransitionLog.objects.get(workorder=workorder)
        self.assertEqual(workorder.status, "cancelled")
        self.assertEqual((log.from_status, log.to_status), ("new", "cancelled"))

    def test_public_selectors_refresh_stale_actor_after_deactivate_and_group_revoke(self):
        workorder = create_workorder_command(
            actor=self.actor,
            payload={
                "board": self.board,
                "department": self.department,
                "title": "Свежий actor",
                "description": "Описание",
            },
        )
        self.assertIn(workorder, list(visible_workorders_queryset(self.actor)))
        self.actor.groups.remove(self.group)
        self.assertNotIn(self.board, list(visible_boards_queryset(self.actor)))
        self.actor.is_active = False
        self.actor.save(update_fields=["is_active"])
        self.assertEqual(list(visible_workorders_queryset(self.actor)), [])

    def test_public_workorder_selector_uses_one_marked_actor_snapshot(self):
        with patch(
            "apps.workorders.selectors.resolve_active_actor",
            wraps=resolve_active_actor,
        ) as resolver:
            list(visible_workorders_queryset(self.actor))
        self.assertEqual(resolver.call_count, 1)

    def test_cross_board_update_rechecks_requested_board_after_sorted_board_locks(self):
        foreign_board = Board.objects.create(title="Чужая доска", slug="foreign-command-board")
        workorder = create_workorder_command(
            actor=self.actor,
            payload={
                "board": self.board,
                "department": self.department,
                "title": "Cross board",
                "description": "Описание",
            },
        )
        with self.assertRaises(PermissionDenied):
            update_workorder_command(
                actor=self.actor,
                workorder_id=workorder.pk,
                payload={"board": foreign_board.pk},
            )

    def test_assignee_is_locked_and_rechecked_as_active_before_save(self):
        assignee = User.objects.create_user(username="racing-assignee", password="pass")
        workorder = create_workorder_command(
            actor=self.actor,
            payload={
                "board": self.board,
                "department": self.department,
                "title": "Assignee race",
                "description": "Описание",
            },
        )
        assignee.is_active = False
        assignee.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            update_workorder_command(
                actor=self.actor,
                workorder_id=workorder.pk,
                payload={"assignee": assignee.pk},
            )

    def test_clone_locks_actor_before_board_and_rechecks_revoked_capability(self):
        self.actor.groups.remove(self.group)
        with self.assertRaises(PermissionDenied):
            clone_board(actor=self.actor, board=self.board, reason="revoke race")
