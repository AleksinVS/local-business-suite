from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from pathlib import Path
from tempfile import TemporaryDirectory

from apps.accounts.models import AccessAssignmentAudit
from apps.accounts.selectors import effective_access_for_user
from apps.accounts.services import apply_role_assignment, preview_role_assignment


class Command(BaseCommand):
    help = "Проверяет сквозной сценарий назначения рискованной роли без сохранения тестовых данных."

    def add_arguments(self, parser):
        parser.add_argument(
            "--viewer-migration",
            action="store_true",
            help="Дополнительно проверить подготовку, включение и откат роли «Наблюдатель».",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        actor_name = "__access_management_e2e_actor__"
        target_name = "__access_management_e2e_target__"
        if User.objects.filter(username__in=[actor_name, target_name]).exists():
            raise CommandError("Тестовые логины уже заняты; команда не будет менять существующих пользователей.")

        with transaction.atomic():
            manager_group, _ = Group.objects.get_or_create(name="manager")
            technical_group, _ = Group.objects.get_or_create(name="__access_management_e2e_technical__")
            actor = User.objects.create_superuser(username=actor_name)
            actor.groups.add(manager_group)
            target = User.objects.create_user(username=target_name)
            target.groups.add(technical_group)

            preview = preview_role_assignment(
                actor=actor,
                target_user=target,
                selected_role_names=["manager"],
                is_staff=True,
                is_superuser=True,
            )
            if not preview["requires_confirmation"]:
                raise CommandError("Роль manager не распознана как рискованная.")

            try:
                apply_role_assignment(
                    actor=actor,
                    target_user=target,
                    selected_role_names=["manager"],
                    is_staff=True,
                    is_superuser=True,
                    preview_token=preview["preview_token"],
                    risk_confirmed=False,
                )
            except ValidationError:
                pass
            else:
                raise CommandError("Рискованная роль применена без подтверждения.")

            target, audit = apply_role_assignment(
                actor=actor,
                target_user=target,
                selected_role_names=["manager"],
                is_staff=True,
                is_superuser=True,
                preview_token=preview["preview_token"],
                risk_confirmed=True,
            )
            group_names = set(target.groups.values_list("name", flat=True))
            if not {"manager", technical_group.name}.issubset(group_names):
                raise CommandError("Роль или техническая группа потеряна при назначении.")
            if not target.is_staff or not target.is_superuser:
                raise CommandError("Технические флаги не применены.")
            access = effective_access_for_user(target)
            if not any(item["code"] == "manage_roles" for item in access["capabilities"]):
                raise CommandError("Итоговый доступ не содержит manage_roles.")
            if not AccessAssignmentAudit.objects.filter(pk=audit.pk, risk_confirmed=True).exists():
                raise CommandError("Audit назначения не создан.")
            if {item["code"] for item in audit.flags_changed} != {"is_staff", "is_superuser"}:
                raise CommandError("Audit не содержит изменения технических флагов.")

            # Решение владельца: активный superuser может назначить роль себе,
            # но только через отдельный рискованный preview/apply и аудит.
            Group.objects.get_or_create(name="admin")
            self_preview = preview_role_assignment(
                actor=actor,
                target_user=actor,
                selected_role_names=["admin"],
            )
            if not any("Самоназначение" in marker for marker in self_preview["risk_markers"]):
                raise CommandError("Самоназначение superuser не помечено отдельным риском.")
            actor, self_audit = apply_role_assignment(
                actor=actor,
                target_user=actor,
                selected_role_names=["admin"],
                preview_token=self_preview["preview_token"],
                risk_confirmed=True,
            )
            if self_audit.actor_id != self_audit.target_user_id:
                raise CommandError("Audit самоназначения не связывает actor и target.")
            try:
                apply_role_assignment(
                    actor=actor,
                    target_user=actor,
                    selected_role_names=["admin"],
                    preview_token=self_preview["preview_token"],
                    risk_confirmed=True,
                )
            except ValidationError:
                pass
            else:
                raise CommandError("Один предпросмотр удалось применить повторно.")

            transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS("access_management_e2e: OK (тестовые данные откатились)"))
        if options.get("viewer_migration"):
            self._viewer_migration_e2e()

    def _viewer_migration_e2e(self):
        """Exercise all migration phases and restore the runtime contract."""
        from apps.core.contract_store import get_contract
        from apps.accounts.models import GroupProfile
        from apps.settings_center.access_migration_services import (
            cutover_explicit_viewer,
            migration_artifact_root,
            prepare_explicit_viewer_migration,
            report_roleless_users,
            rollback_explicit_viewer,
        )
        from apps.settings_center.models import SettingsChange

        User = get_user_model()
        actor = User.objects.create_superuser(username="__viewer_migration_e2e_actor__")
        target = User.objects.create_user(username="__viewer_migration_e2e_target__")
        manifest_path = None
        cutover_done = False
        try:
            with TemporaryDirectory(dir=migration_artifact_root()) as tmp:
                manifest_path = Path(tmp) / "viewer-manifest.json"
                report = report_roleless_users()
                for row in report["users"]:
                    row["choice"] = "viewer" if row["id"] == target.pk else "no_role"
                for row in report["customer_open_boards"]:
                    row["add_viewer"] = False
                prepared = prepare_explicit_viewer_migration(
                    actor=actor,
                    manifest=report,
                    reason="management e2e",
                    output_path=manifest_path,
                )
                cutover = cutover_explicit_viewer(actor=actor, manifest=prepared, reason="management e2e")
                cutover_done = True
                if "viewer" not in get_contract("role_rules"):
                    raise CommandError("Viewer contract was not activated by e2e.")
                rollback = rollback_explicit_viewer(actor=actor, manifest=cutover, reason="management e2e")
                if rollback.get("rolled_back") is not True or "viewer" in get_contract("role_rules"):
                    raise CommandError("Viewer rollback did not restore compatibility phase.")
        finally:
            # Migration audits use PROTECT, so remove only these test rows after
            # the contract has been restored.  No production/runtime data is
            # touched by this command's test fixtures.
            AccessAssignmentAudit.objects.filter(target_user__in=[actor, target]).delete()
            SettingsChange.objects.filter(actor__in=[actor, target], rollback_of__isnull=False).delete()
            SettingsChange.objects.filter(actor__in=[actor, target]).delete()
            viewer = Group.objects.filter(name="viewer").first()
            if viewer is not None:
                GroupProfile.objects.filter(group=viewer).delete()
                viewer.delete()
            User.objects.filter(pk__in=[actor.pk, target.pk]).delete()
        self.stdout.write(self.style.SUCCESS("access_management_e2e viewer migration: OK"))
