import json
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test import Client, override_settings
from django.urls import reverse

from apps.core.contract_store import _reset_for_tests
from apps.core.json_utils import load_json_file
from apps.core.models import Department
from apps.memory.models import MemoryGroupMembershipAudit
from apps.settings_center.models import SettingsChange
from apps.workorders.models import Board, BoardAccessAudit, WorkOrder


class Command(BaseCommand):
    help = "Сквозная HTTP-проверка редактора роли, доступа к доске и технических групп памяти."

    @classmethod
    def _response_context(cls, response, *, label):
        """Вернуть контекст TemplateResponse и тестового Django Client."""
        status_code = getattr(response, "status_code", None)
        if status_code != 200:
            raise CommandError(
                f"HTTP-проверка вернула статус {status_code}: {label}. Ожидался 200."
            )
        for candidate in (
            getattr(response, "context_data", None),
            getattr(response, "context", None),
        ):
            context = cls._normalize_response_context(candidate)
            if context is not None:
                return context
        raise CommandError(f"HTTP-проверка не вернула поддерживаемый контекст: {label}.")

    @classmethod
    def _normalize_response_context(cls, context):
        if context is None:
            return None
        if isinstance(context, Mapping):
            return dict(context)
        if hasattr(context, "flatten"):
            flattened = context.flatten()
            return dict(flattened) if isinstance(flattened, Mapping) else None
        if isinstance(context, (list, tuple)):
            # ContextList ищет ключ сначала в первом под-контексте. Обратный
            # порядок update сохраняет именно этот приоритет в итоговом dict.
            normalized = {}
            for item in reversed(context):
                item_context = cls._normalize_response_context(item)
                if item_context is None:
                    return None
                normalized.update(item_context)
            return normalized
        return None

    def handle(self, *args, **options):
        required_tables = {
            BoardAccessAudit._meta.db_table,
            MemoryGroupMembershipAudit._meta.db_table,
            SettingsChange._meta.db_table,
        }
        missing_tables = required_tables - set(connection.introspection.table_names())
        if missing_tables:
            raise CommandError(
                "Сначала примените миграции; отсутствуют таблицы: "
                + ", ".join(sorted(missing_tables))
            )
        user_model = get_user_model()
        names = {
            "actor": "__access_admin_e2e_root__",
            "member": "__access_admin_e2e_member__",
            "control": "__access_admin_e2e_control__",
        }
        if user_model.objects.filter(username__in=names.values()).exists():
            raise CommandError("Тестовые логины уже заняты; существующие данные не изменены.")

        role_rules = load_json_file("contracts/role_rules.json")
        role_code = "technician"
        control_role_code = "manager"
        if role_rules.get(role_code, {}).get("view_scope") != "assigned_or_unassigned_or_authored":
            raise CommandError("E2E ожидает исходную ограниченную область technician.view_scope.")

        actor = member = control = board = department = None
        created_group_names = []
        try:
            for group_name in (
                role_code,
                control_role_code,
                "customer",
                "memory_observer",
            ):
                group, created = Group.objects.get_or_create(name=group_name)
                if created:
                    created_group_names.append(group_name)

            actor = user_model.objects.create_superuser(username=names["actor"])
            member = user_model.objects.create_user(username=names["member"])
            control = user_model.objects.create_user(username=names["control"])
            member.groups.add(Group.objects.get(name=role_code))
            control.groups.add(
                Group.objects.get(name=role_code),
                Group.objects.get(name=control_role_code),
            )
            department = Department.objects.create(name="__access-admin-e2e-department__")
            board = Board.objects.create(
                title="Сквозная проверка доступа",
                slug="__access-admin-e2e-board__",
            )
            board.allowed_groups.add(
                Group.objects.get(name="customer"),
                Group.objects.get(name=role_code),
                Group.objects.get(name=control_role_code),
            )
            workorder = WorkOrder.objects.create(
                title="Сквозная проверка области роли",
                description="Заявка назначена другому пользователю.",
                department=department,
                author=actor,
                assignee=actor,
                board=board,
            )

            with TemporaryDirectory() as tmpdir:
                runtime_root = Path(tmpdir)
                role_file = runtime_root / "role_rules.json"
                role_file.write_text(json.dumps(role_rules, ensure_ascii=False), encoding="utf-8")
                with override_settings(
                    ALLOWED_HOSTS=["testserver"],
                    RUNTIME_CONTRACTS_DIR=runtime_root,
                    LOCAL_BUSINESS_ROLE_RULES_FILE=role_file,
                ):
                    _reset_for_tests()
                    client = Client()

                    client.force_login(member)
                    detail_url = reverse("workorders:detail", args=[workorder.pk])
                    if client.get(detail_url).status_code != 404:
                        raise CommandError("До изменения technician видит чужую назначенную заявку.")
                    client.force_login(control)
                    if client.get(detail_url).status_code != 200:
                        raise CommandError("Участник technician+manager потерял доступ manager.")

                    client.force_login(actor)
                    role_url = reverse("settings_center:role_definition", args=[role_code])
                    page = client.get(role_url)
                    page_context = self._response_context(page, label="страница роли")
                    form = page_context["form"]
                    role_post = {
                        "action": "preview",
                        "base_hash": page_context["role"]["base_hash"],
                    }
                    for field_name in form.fields:
                        if not field_name.startswith("capability__"):
                            continue
                        code = field_name.removeprefix("capability__")
                        value = role_rules[role_code][code]
                        if code == "view_scope":
                            value = "all"
                        if value is True:
                            role_post[field_name] = "on"
                        elif value == "*":
                            role_post[field_name] = ["*"]
                        elif isinstance(value, list):
                            role_post[field_name] = value
                        elif value is not False and value is not None:
                            role_post[field_name] = value
                    preview_response = client.post(role_url, role_post)
                    preview = self._response_context(
                        preview_response, label="предпросмотр роли"
                    ).get("preview")
                    if not preview or preview["impact"]["role_member_count"] != 2:
                        raise CommandError("Role preview не показал двух уникальных участников роли.")
                    if preview["impact"]["effective_change_count"] != 1:
                        raise CommandError("Role preview неверно посчитал реально затронутого пользователя.")
                    if preview["impact"]["unchanged_by_other_role_count"] != 1:
                        raise CommandError("Role preview не учёл сохраняющий доступ manager.")
                    role_post.update(
                        action="apply",
                        preview_token=preview["preview_token"],
                        risk_confirmed="on",
                    )
                    if client.post(role_url, role_post).status_code != 302:
                        raise CommandError("Изменение одной роли не применилось через HTTP.")

                    client.force_login(member)
                    if client.get(detail_url).status_code != 200:
                        raise CommandError("Расширенная область technician не сработала через HTTP.")
                    client.force_login(control)
                    if client.get(detail_url).status_code != 200:
                        raise CommandError("Совмещённая роль technician+manager потеряла доступ.")

                    client.force_login(actor)
                    board_url = reverse("settings_center:board_access", args=[board.pk])
                    board_data = {
                        "action": "preview",
                        "group_names": [role_code, control_role_code],
                        "reason": "Сквозная проверка доступа к доске.",
                    }
                    board_preview_response = client.post(board_url, board_data)
                    board_preview = self._response_context(
                        board_preview_response, label="предпросмотр доски"
                    ).get("preview")
                    if not board_preview:
                        raise CommandError("Board preview не сформирован.")
                    board_data.update(
                        action="apply",
                        preview_token=board_preview["preview_token"],
                        risk_confirmed="on",
                    )
                    if client.post(board_url, board_data).status_code != 302:
                        raise CommandError("Доступ к доске не применился через HTTP.")

                    memory_url = reverse(
                        "settings_center:memory_group_membership", args=[member.pk]
                    )
                    memory_data = {
                        "action": "preview",
                        "group_names": ["memory_observer"],
                        "reason": "Сквозная проверка экспертного назначения.",
                    }
                    memory_preview_response = client.post(memory_url, memory_data)
                    memory_preview = self._response_context(
                        memory_preview_response, label="предпросмотр технической группы"
                    ).get("preview")
                    if not memory_preview:
                        raise CommandError("Memory membership preview не сформирован.")
                    memory_data.update(
                        action="apply",
                        preview_token=memory_preview["preview_token"],
                        confirmed="on",
                    )
                    if client.post(memory_url, memory_data).status_code != 302:
                        raise CommandError("Техническая группа памяти не применилась через HTTP.")

                    if not SettingsChange.objects.filter(
                        setting_id="core.contract.role_rules",
                        status=SettingsChange.Status.APPLIED,
                    ).exists():
                        raise CommandError("SettingsChange для роли не создан.")
                    if not BoardAccessAudit.objects.filter(board=board).exists():
                        raise CommandError("BoardAccessAudit не создан.")
                    if not MemoryGroupMembershipAudit.objects.filter(target_user=member).exists():
                        raise CommandError("MemoryGroupMembershipAudit не создан.")
        finally:
            _reset_for_tests()
            if board is not None:
                BoardAccessAudit.objects.filter(board=board).delete()
                board.delete()
            if member is not None:
                MemoryGroupMembershipAudit.objects.filter(target_user=member).delete()
            SettingsChange.objects.filter(actor=actor).delete() if actor is not None else None
            for user in (member, control, actor):
                if user is not None:
                    user.delete()
            if department is not None:
                department.delete()
            if created_group_names:
                Group.objects.filter(name__in=created_group_names).delete()

        self.stdout.write(
            self.style.SUCCESS("access_administration_e2e: OK (тестовые данные удалены)")
        )
