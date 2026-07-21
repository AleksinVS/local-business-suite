from django.core.management.base import BaseCommand

from apps.analytics.services import reflect_knowledge


class Command(BaseCommand):
    help = "Reflect over knowledge/analytics facts and propose metric candidates."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report candidates without persisting them.")

    def handle(self, *args, **options):
        result = reflect_knowledge(dry_run=options["dry_run"])
        self.stdout.write(
            "Analytics reflection finished "
            f"candidates={result['candidates']} dry_run={result['dry_run']}"
        )
