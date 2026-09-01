from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from apps.warehouse.services import rebuild_stock_balances, stock_balance_mismatches


class Command(BaseCommand):
    help = "Пересобрать текущие складские остатки из неизменяемого журнала."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True, help="Имя пользователя-инициатора")
        parser.add_argument("--department-id", type=int)
        parser.add_argument(
            "--check",
            action="store_true",
            help="Только сравнить проекцию с журналом, ничего не изменяя.",
        )

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("Пользователь-инициатор не найден.")
        try:
            if options["check"]:
                mismatches = stock_balance_mismatches(
                    actor=actor, department_id=options.get("department_id")
                )
                if mismatches:
                    raise CommandError(
                        f"Проекция расходится с журналом: {len(mismatches)} ключей."
                    )
                self.stdout.write(self.style.SUCCESS("Проекция остатков согласована с журналом."))
                return
            count = rebuild_stock_balances(
                actor=actor, department_id=options.get("department_id")
            )
        except (PermissionDenied, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Пересобрано остатков: {count}."))
