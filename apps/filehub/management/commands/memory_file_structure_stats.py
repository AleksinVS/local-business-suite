from django.core.management.base import BaseCommand, CommandError

from apps.filehub.file_organization_stats import build_organization_proposals
from apps.memory.models import MemorySource


class Command(BaseCommand):
    help = "Aggregate file virtual structure usage and create organization proposals."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", required=True, help="MemorySource code.")
        parser.add_argument("--dry-run", action="store_true", help="Show metrics without writing proposals.")
        parser.add_argument("--allow-disabled", action="store_true", help="Allow disabled file organization profile.")

    def handle(self, *args, **options):
        source = _source(options["source_code"])
        metrics = build_organization_proposals(
            source=source,
            dry_run=options["dry_run"],
            require_enabled=not options["allow_disabled"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Memory file structure stats "
                f"{'dry-run ' if options['dry_run'] else ''}finished for {source.code}: "
                f"candidate_buckets={metrics['candidate_buckets']}, proposals={metrics['proposals']}, "
                f"below_threshold={metrics['below_threshold']}"
            )
        )


def _source(source_code: str):
    try:
        return MemorySource.objects.get(code=source_code)
    except MemorySource.DoesNotExist as exc:
        raise CommandError(f"MemorySource '{source_code}' does not exist.") from exc
