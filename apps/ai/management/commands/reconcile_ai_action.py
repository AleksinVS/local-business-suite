from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.ai.models import AgentActionLog, PendingAction
from apps.ai.services import record_action


class Command(BaseCommand):
    help = (
        "Записать операторское наблюдение по AI-действию без небезопасного "
        "закрытия состояния reconciliation_required."
    )

    def add_arguments(self, parser):
        parser.add_argument("--token", required=True)
        parser.add_argument("--outcome", choices=("succeeded", "failed"), required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--operator", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        reason = str(options["reason"] or "").strip()
        if len(reason) < 10:
            raise CommandError("Укажите содержательную причину сверки (не менее 10 символов).")
        try:
            pending = PendingAction.objects.select_related("actor", "session").get(
                token=options["token"]
            )
        except (PendingAction.DoesNotExist, ValueError) as exc:
            raise CommandError("AI-действие не найдено.") from exc
        if pending.status != PendingAction.Status.RECONCILIATION_REQUIRED:
            raise CommandError("Сверять можно только действие со статусом reconciliation_required.")
        try:
            operator = get_user_model().objects.get(username=options["operator"])
        except get_user_model().DoesNotExist as exc:
            raise CommandError("Оператор сверки не найден.") from exc
        if not operator.is_active or not operator.is_superuser:
            raise CommandError("Оператор сверки должен быть активным суперпользователем.")
        if options["dry_run"]:
            self.stdout.write(
                f"AI action {pending.token}: {pending.tool_code}, "
                f"наблюдение={options['outcome']}, статус останется {pending.status} (dry-run)"
            )
            return
        with transaction.atomic():
            locked = PendingAction.objects.select_for_update().get(pk=pending.pk)
            if locked.status != PendingAction.Status.RECONCILIATION_REQUIRED:
                raise CommandError("Статус действия изменился во время сверки.")
            record_action(
                actor=operator,
                tool_code=locked.tool_code,
                action_kind=locked.action_kind,
                status=AgentActionLog.Status.PENDING,
                request_payload={
                    "pending_token": str(locked.token),
                    "manual_reconciliation": True,
                    "original_actor_id": locked.actor_id,
                },
                response_payload={
                    "manual_reconciliation": True,
                    "observed_outcome": options["outcome"],
                    "reason": reason,
                    "state_closed": False,
                },
                session=locked.session,
                message=None,
                error_message="",
            )
        self.stdout.write(
            self.style.WARNING(
                f"AI action {locked.token}: наблюдение записано; статус "
                "reconciliation_required сохранён до появления fencing-протокола."
            )
        )
