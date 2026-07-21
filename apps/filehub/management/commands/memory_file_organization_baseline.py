from django.core.management.base import BaseCommand, CommandError

from apps.filehub.file_organization_baseline import build_baseline_virtual_structure
from apps.memory.models import MemorySource


class Command(BaseCommand):
    help = "Build generated baseline virtual file structure for a file memory source."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", required=True, help="MemorySource code.")
        parser.add_argument("--dry-run", action="store_true", help="Show metrics without writing placements.")
        parser.add_argument("--limit", type=int, default=None, help="Optional maximum source objects to process.")
        parser.add_argument("--allow-disabled", action="store_true", help="Allow disabled file organization profile.")

    def handle(self, *args, **options):
        source = _source(options["source_code"])
        metrics = build_baseline_virtual_structure(
            source=source,
            dry_run=options["dry_run"],
            limit=options["limit"],
            require_enabled=not options["allow_disabled"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Memory file baseline "
                f"{'dry-run ' if options['dry_run'] else ''}finished for {source.code}: "
                f"seen={metrics['seen']}, placements={metrics['placements']}, "
                f"review_required={metrics['review_required']}, issues={metrics['issues']}"
            )
        )


def _source(source_code: str):
    try:
        return MemorySource.objects.get(code=source_code)
    except MemorySource.DoesNotExist as exc:
        raise CommandError(f"MemorySource '{source_code}' does not exist.") from exc
