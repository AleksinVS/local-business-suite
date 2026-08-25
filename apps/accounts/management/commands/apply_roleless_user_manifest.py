from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.settings_center.access_migration_services import prepare_explicit_viewer_migration


class Command(BaseCommand):
    help = "Apply an owner-approved roleless-user manifest in the inert prepared phase."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--actor-id", required=True, type=int)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--output", help="Prepared manifest output path.")

    def handle(self, *args, **options):
        User = get_user_model()
        actor = User.objects.filter(pk=options["actor_id"]).first()
        if actor is None:
            raise CommandError("Actor does not exist.")
        try:
            result = prepare_explicit_viewer_migration(
                actor=actor,
                manifest=options["manifest"],
                reason=options["reason"],
                output_path=options.get("output") or options["manifest"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Подготовка завершена: operation_id={result['operation_id']}, "
            f"users={len(result.get('added_users', []))}, boards={len(result.get('added_boards', []))}, "
            f"path={result['operation_path']}"
        ))
