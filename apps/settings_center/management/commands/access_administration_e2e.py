import copy
import json
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test import Client, override_settings
from django.urls import reverse

from apps.core.contract_store import _reset_for_tests
from apps.core.json_utils import load_json_file
from apps.settings_center.document_hashes import document_hash
from apps.settings_center.document_registry import get_document_registry
from apps.settings_center.document_repository import get_fresh_document
from apps.core.models import Department
from apps.memory.models import MemoryGroupMembershipAudit
from apps.settings_center.models import RuntimeSettingDocument, SettingsChange
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

    @transaction.atomic
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
            "actor": "e2e_access_admin_root",
            "member": "e2e_access_admin_member",
            "control": "e2e_access_admin_control",
        }
        if user_model.objects.filter(username__in=names.values()).exists():
            raise CommandError("Тестовые логины уже заняты; существующие данные не изменены.")

        role_snapshot = get_fresh_document("core.contract.role_rules")
        role_rules = role_snapshot.payload
        role_spec = get_document_registry().get("core.contract.role_rules")
        database_backend = role_spec.active_backend == "database"
        source_role_code = "technician"
        role_code = "e2e_access_technician"
        copy_role_code = "e2e_access_technician_copy"
        source_control_role_code = "manager"
        control_role_code = "e2e_access_manager"
        source_role = role_rules.get(source_role_code)
        source_control_role = role_rules.get(source_control_role_code)
        if not isinstance(source_role, dict) or source_role.get("view_scope") != "assigned_or_unassigned_or_authored":
            raise CommandError("E2E ожидает исходную ограниченную область technician.view_scope.")
        if not isinstance(source_control_role, dict):
            raise CommandError("E2E ожидает исходную контрактную роль manager.")
        temporary_role_codes = (role_code, control_role_code, copy_role_code)
        if any(
            code in role_rules or Group.objects.filter(name=code).exists()
            for code in temporary_role_codes
        ):
            raise CommandError("Временная роль E2E уже занята; существующие данные не изменены.")
        role_rules[role_code] = copy.deepcopy(source_role)
        role_rules[control_role_code] = copy.deepcopy(source_control_role)
        if database_backend:
            # The command runs inside one outer transaction and rolls it back
            # after the assertions.  Seed the temporary roles in the backend
            # that production requests actually use; a file-only fixture would
            # be ignored after DB cutover and give a false 404.
            RuntimeSettingDocument.objects.update_or_create(
                document_id="core.contract.role_rules",
                defaults={
                    "schema_version": role_spec.schema_version,
                    "payload": role_rules,
                    "revision": max(role_snapshot.revision + 1, 1),
                    "content_hash": document_hash(role_rules),
                    "default_hash": role_snapshot.default_hash,
                    "updated_by": None,
                },
            )

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
            department = Department.objects.create(name="e2e-access-admin-department")
            board = Board.objects.create(
                title="Сквозная проверка доступа",
                slug="e2e-access-admin-board",
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
                    control_detail_status = client.get(detail_url).status_code
                    if control_detail_status != 200:
                        from apps.workorders.policies import allowed_view_scopes, user_roles
                        from apps.workorders.selectors import visible_boards_queryset

                        raise CommandError(
                            "Участник временных technician+manager потерял контрольный доступ: "
                            f"status={control_detail_status}, "
                            f"roles={sorted(user_roles(control))}, "
                            f"scopes={sorted(allowed_view_scopes(control))}, "
                            f"visible_boards={list(visible_boards_queryset(control).values_list('pk', flat=True))}, "
                            f"target_board={board.pk}."
                        )

                    client.force_login(actor)
                    role_url = reverse("settings_center:access_workspace")
                    role_query = {
                        "view": "roles",
                        "object": role_code,
                        "field": "definition",
                        "panel": "field",
                    }
                    page = client.get(role_url, role_query)
                    page_context = self._response_context(page, label="страница роли")
                    form = page_context["field_form"]
                    role_post = {
                        "action": "save",
                        **role_query,
                        "base_hash": form.initial.get("base_hash") or form["base_hash"].value(),
                        "base_revision": (
                            form.initial.get("base_revision")
                            or form["base_revision"].value()
                        ),
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
                    role_response = client.post(role_url, role_post)
                    if role_response.status_code != 302:
                        response_context = self._normalize_response_context(
                            getattr(role_response, "context_data", None)
                            or getattr(role_response, "context", None)
                        ) or {}
                        response_form = response_context.get("field_form")
                        form_errors = (
                            response_form.errors.get_json_data()
                            if response_form is not None
                            else {}
                        )
                        raise CommandError(
                            "Изменение одной роли не сохранилось через HTTP: "
                            f"status={role_response.status_code}, errors={form_errors}, "
                            f"editor_error={response_context.get('editor_error', '')!r}."
                        )

                    copy_query = {"view": "roles", "copy": source_role_code, "panel": "inspector"}
                    copy_page = client.get(role_url, copy_query)
                    copy_context = self._response_context(copy_page, label="форма копирования роли")
                    copy_form = copy_context["field_form"]
                    copy_post = {
                        "action": "copy_role",
                        **copy_query,
                        "source_role_code": source_role_code,
                        "code": copy_role_code,
                        "display_name": "Копия technician",
                        "description": "E2E копия без назначений",
                        "base_hash": copy_form["base_hash"].value(),
                        "base_revision": copy_form["base_revision"].value(),
                    }
                    if client.post(role_url, copy_post).status_code != 302:
                        raise CommandError("Копирование роли не сохранилось через HTTP.")
                    created_group_names.append(copy_role_code)
                    expected_copy = copy.deepcopy(source_role)
                    expected_copy.update({"display_name": "Копия technician", "description": "E2E копия без назначений"})
                    updated_roles = (
                        get_fresh_document("core.contract.role_rules").payload
                        if database_backend
                        else load_json_file(role_file)
                    )
                    if updated_roles.get(copy_role_code) != expected_copy:
                        raise CommandError("Определение копии не совпадает с источником.")
                    if Group.objects.get(name=copy_role_code).user_set.exists():
                        raise CommandError("Копия роли неожиданно получила участников.")
                    if board.allowed_groups.filter(name=copy_role_code).exists():
                        raise CommandError("Копия роли неожиданно получила ACL доски.")

                    client.force_login(member)
                    if client.get(detail_url).status_code != 200:
                        raise CommandError("Расширенная область technician не сработала через HTTP.")
                    client.force_login(control)
                    if client.get(detail_url).status_code != 200:
                        raise CommandError("Совмещённая роль technician+manager потеряла доступ.")

                    client.force_login(actor)
                    board_url = reverse("settings_center:access_workspace")
                    board_query = {
                        "view": "boards",
                        "object": board.pk,
                        "field": "groups",
                        "panel": "field",
                    }
                    board_data = {
                        "action": "save",
                        **board_query,
                        "group_names": [role_code, control_role_code],
                    }
                    if client.post(board_url, board_data).status_code != 302:
                        raise CommandError("Доступ к доске не сохранился через HTTP.")

                    memory_url = reverse("settings_center:access_workspace")
                    memory_query = {
                        "view": "users",
                        "object": member.pk,
                        "field": "memory-groups",
                        "panel": "field",
                    }
                    memory_data = {
                        "action": "save",
                        **memory_query,
                        "group_names": ["memory_observer"],
                    }
                    if client.post(memory_url, memory_data).status_code != 302:
                        raise CommandError("Техническая группа памяти не сохранилась через HTTP.")

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
            if database_backend:
                # Includes the temporary RuntimeSettingDocument, UI writes,
                # audits and every E2E fixture.  A failure also exits the
                # atomic block by exception and therefore cannot leak state.
                transaction.set_rollback(True)
            else:
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
