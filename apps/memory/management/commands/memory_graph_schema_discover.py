import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.memory.document_ingestion import discover_schema_proposals_from_package


class Command(BaseCommand):
    help = "Create moderated graph schema proposals from a prepared bootstrap package."

    def add_arguments(self, parser):
        parser.add_argument("--package", required=True, help="Path to bootstrap package JSON.")
        parser.add_argument("--dry-run", action="store_true", help="Show proposals without writing review records.")

    def handle(self, *args, **options):
        package_path = Path(options["package"])
        if not package_path.exists():
            raise CommandError(f"Bootstrap package does not exist: {package_path}")
        package = json.loads(package_path.read_text(encoding="utf-8"))
        result = discover_schema_proposals_from_package(package=package, dry_run=options["dry_run"])
        self.stdout.write(
            self.style.SUCCESS(
                "Memory graph schema discovery "
                f"{'dry-run ' if options['dry_run'] else ''}finished: proposals={result['proposal_count']}"
            )
        )
