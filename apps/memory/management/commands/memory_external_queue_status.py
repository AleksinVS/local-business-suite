from django.core.management.base import BaseCommand

from apps.memory.external_connectors import get_external_queue_backend


class Command(BaseCommand):
    help = "Print external connector queue status counts."

    def handle(self, *args, **options):
        stats = get_external_queue_backend().stats()
        if not stats:
            self.stdout.write("External connector queue is empty.")
            return
        for status, count in sorted(stats.items()):
            self.stdout.write(f"{status}: {count}")
