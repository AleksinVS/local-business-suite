import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from apps.warehouse.services import (
    inline_series_reconciliation,
    record_inline_series_checkpoint,
)


class Command(BaseCommand):
    help = "Сверить журнал и остатки после перехода на inline-серии."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True, help="Имя пользователя-инициатора")
        parser.add_argument("--department-id", type=int)
        parser.add_argument(
            "--record-checkpoint",
            action="store_true",
            help="Записать успешную сверку в складской аудит.",
        )

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("Пользователь-инициатор не найден.")
        try:
            operation = (
                record_inline_series_checkpoint
                if options["record_checkpoint"]
                else inline_series_reconciliation
            )
            report = operation(
                actor=actor,
                department_id=options.get("department_id"),
            )
        except (PermissionDenied, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if not report["ok"]:
            raise CommandError("Сверка inline-серий завершилась с расхождениями.")
        self.stdout.write(self.style.SUCCESS("Inline-серии согласованы с журналом."))
