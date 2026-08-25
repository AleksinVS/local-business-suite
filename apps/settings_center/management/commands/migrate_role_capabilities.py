from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.settings_center.contract_services import migrate_role_capability_catalog


class Command(BaseCommand):
    help = (
        "Deployment-only migration of the frozen role capability catalog. "
        "The command prints hashes and audit identifiers, never contract payloads."
    )

    def add_arguments(self, parser):
        parser.add_argument("--operator-id", required=True, type=int)
        parser.add_argument("--candidate", required=True, type=Path)
        parser.add_argument("--expected-runtime-catalog-hash", required=True)
        parser.add_argument("--expected-git-catalog-hash", required=True)
        parser.add_argument("--expected-runtime-hash", required=True)
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        operator = get_user_model().objects.filter(pk=options["operator_id"]).first()
        if operator is None:
            raise CommandError("Active superuser operator was not found.")
        try:
            result = migrate_role_capability_catalog(
                actor=operator,
                candidate_path=options["candidate"],
                expected_runtime_catalog_hash=options["expected_runtime_catalog_hash"],
                expected_git_catalog_hash=options["expected_git_catalog_hash"],
                expected_runtime_hash=options["expected_runtime_hash"],
                reason=options["reason"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        change = result["change"]
        self.stdout.write(
            self.style.SUCCESS(
                "Capability catalog migration applied: "
                f"settings_change_id={change.pk}; "
                f"before={change.before_hash[:12]}; after={change.after_hash[:12]}; "
                f"backup={result['backup_path'].name}"
            )
        )
