from django.core.management.base import BaseCommand

from apps.analytics.services import extract_analytics_source


class Command(BaseCommand):
    help = "Extract knowledge and analytics facts from an analytics source."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", required=True, help="Analytics source code to extract.")
        parser.add_argument("--dry-run", action="store_true", help="Run extraction without persisting packets/facts.")

    def handle(self, *args, **options):
        result = extract_analytics_source(source_code=options["source_code"], dry_run=options["dry_run"])
        self.stdout.write(
            "Analytics extraction finished "
            f"run_id={result['run_id']} packets={result['packets']} facts={result['facts']} dry_run={result['dry_run']}"
        )
