from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.settings_center.access_migration_services import cutover_explicit_viewer, _private_artifact_path, _private_write


class Command(BaseCommand):
    help = "Atomically add the exact Git-default viewer role to the runtime contract."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--actor-id", required=True, type=int)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--output")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(pk=options["actor_id"]).first()
        if actor is None:
            raise CommandError("Actor does not exist.")
        try:
            result = cutover_explicit_viewer(
                actor=actor,
                manifest=options["manifest"],
                reason=options["reason"],
            )
            if options.get("output"):
                _private_write(_private_artifact_path(options["output"]), result)
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Cutover завершён: operation_id={result['operation_id']}, "
            f"change_id={result['cutover_change_id']}, path={result['operation_path']}"
        ))
