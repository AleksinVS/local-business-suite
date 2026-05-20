from django.core.management.base import BaseCommand

from apps.memory.external_connectors import ExternalJobStatus, get_external_queue_backend


class Command(BaseCommand):
    help = "Print external connector queue status counts."

    def add_arguments(self, parser):
        parser.add_argument("--details", action="store_true", help="Show recent failed/dead-letter jobs.")
        parser.add_argument("--limit", type=int, default=20, help="Maximum detailed jobs to show.")

    def handle(self, *args, **options):
        backend = get_external_queue_backend()
        stats = backend.stats()
        if not stats:
            self.stdout.write("External connector queue is empty.")
        else:
            for status, count in sorted(stats.items()):
                self.stdout.write(f"{status}: {count}")

        if not options["details"]:
            return

        jobs = backend.list_recent(
            statuses=[ExternalJobStatus.FAILED, ExternalJobStatus.DEAD_LETTER, ExternalJobStatus.RETRY_WAIT],
            limit=options["limit"],
        )
        if not jobs:
            self.stdout.write("No recent failed/dead-letter external connector jobs.")
            return
        self.stdout.write("Recent failed/dead-letter external connector jobs:")
        for job in jobs:
            self.stdout.write(
                f"{job.status} job_id={job.job_id} source={job.source_code} "
                f"kind={job.job_kind} attempts={job.attempt_count}/{job.max_attempts} "
                f"request_id={job.request_id} error={job.error_message}"
            )
