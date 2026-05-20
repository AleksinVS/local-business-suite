from django.core.management.base import BaseCommand

from apps.memory.external_connectors import process_external_connector_jobs


class Command(BaseCommand):
    help = "Process queued external connector jobs from the configured external queue backend."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10, help="Maximum jobs to lease and process.")
        parser.add_argument("--lease-seconds", type=int, default=300, help="Lease duration for running jobs.")
        parser.add_argument("--dry-run", action="store_true", help="Show that the worker is available without leasing jobs.")

    def handle(self, *args, **options):
        limit = max(1, int(options["limit"]))
        lease_seconds = max(30, int(options["lease_seconds"]))
        if options["dry_run"]:
            self.stdout.write(
                f"External connector worker dry-run: limit={limit}, lease_seconds={lease_seconds}"
            )
            return

        results = process_external_connector_jobs(limit=limit, lease_seconds=lease_seconds)
        succeeded = sum(1 for item in results if item.get("status") == "succeeded")
        failed = len(results) - succeeded
        self.stdout.write(
            self.style.SUCCESS(
                f"External connector worker finished: processed={len(results)}, succeeded={succeeded}, failed={failed}"
            )
        )
