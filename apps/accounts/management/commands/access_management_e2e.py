from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import AccessAssignmentAudit
from apps.accounts.selectors import effective_access_for_user
from apps.accounts.services import apply_role_assignment, preview_role_assignment


class Command(BaseCommand):
    help = "Проверяет сквозной сценарий назначения рискованной роли без сохранения тестовых данных."

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

            transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS("access_management_e2e: OK (тестовые данные откатились)"))
