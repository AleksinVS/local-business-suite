from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.settings_center.contract_services import (
    migrate_role_administration_metadata,
)


class Command(BaseCommand):
    help = "Remove inert legacy role administration metadata during deployment."

    def add_arguments(self, parser):
        parser.add_argument("--operator-id", required=True, type=int)
        parser.add_argument("--expected-runtime-hash", required=True)
        parser.add_argument("--expected-git-hash", required=True)
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        operator = get_user_model().objects.filter(pk=options["operator_id"]).first()
        if operator is None:
            raise CommandError("Active superuser operator was not found.")
        try:
            result = migrate_role_administration_metadata(
                actor=operator,
                expected_runtime_hash=options["expected_runtime_hash"],
                expected_git_hash=options["expected_git_hash"],
                reason=options["reason"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        change = result["change"]
        self.stdout.write(
            self.style.SUCCESS(
                "Legacy role administration removed: "
                f"settings_change_id={change.pk}; "
                f"before={change.before_hash[:12]}; after={change.after_hash[:12]}; "
                f"backup={result['backup_path'].name}"
            )
        )
