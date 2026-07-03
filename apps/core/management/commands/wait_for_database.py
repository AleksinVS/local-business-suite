import time

from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections


class Command(BaseCommand):
    help = "Wait until the default database accepts connections."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=int,
            default=60,
            help="Maximum number of seconds to wait.",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=1.0,
            help="Delay between connection attempts in seconds.",
        )

    def handle(self, *args, **options):
        deadline = time.monotonic() + options["timeout"]
        last_error = None

        while time.monotonic() < deadline:
            try:
                connection = connections[DEFAULT_DB_ALIAS]
                connection.ensure_connection()
                self.stdout.write(self.style.SUCCESS("Database is available."))
                return
            except Exception as exc:  # noqa: BLE001 - command reports the last connection failure
                last_error = exc
                time.sleep(options["interval"])

        raise CommandError(f"Database did not become available: {last_error}")
