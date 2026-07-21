from django.core.management.base import BaseCommand, CommandError

from apps.filehub.file_organization_incoming import process_incoming_folder
from apps.memory.models import MemorySource


class Command(BaseCommand):
    help = "Process incoming folder for file source auto organization."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", required=True, help="MemorySource code.")
        parser.add_argument("--dry-run", action="store_true", help="Show metrics without writing state.")
        parser.add_argument("--limit", type=int, default=None, help="Optional maximum files to process.")
        parser.add_argument("--allow-disabled", action="store_true", help="Allow disabled file organization profile.")

    def handle(self, *args, **options):
        source = _source(options["source_code"])
        metrics = process_incoming_folder(
            source=source,
            dry_run=options["dry_run"],
            limit=options["limit"],
            require_enabled=not options["allow_disabled"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Memory file incoming "
                f"{'dry-run ' if options['dry_run'] else ''}finished for {source.code}: "
                f"seen={metrics['seen']}, stable={metrics['stable']}, placements={metrics['placements']}, "
                f"blocked={metrics['blocked']}, review_required={metrics['review_required']}, issues={metrics['issues']}"
            )
        )


def _source(source_code: str):
    try:
        return MemorySource.objects.get(code=source_code)
    except MemorySource.DoesNotExist as exc:
        raise CommandError(f"MemorySource '{source_code}' does not exist.") from exc
