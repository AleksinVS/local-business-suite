from django.core.management.base import BaseCommand, CommandError

from apps.filehub.file_organization_move import purge_ready_source_files, run_move_worker
from apps.memory.models import MemorySource


class Command(BaseCommand):
    help = "Run approved managed_fs file move jobs and optional source purge."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", required=True, help="MemorySource code.")
        parser.add_argument("--dry-run", action="store_true", help="Show metrics without moving or purging files.")
        parser.add_argument("--limit", type=int, default=None, help="Optional maximum move jobs to process.")
        parser.add_argument("--purge", action="store_true", help="Purge quarantined source files after retention.")
        parser.add_argument("--backup-checkpoint-ref", default="", help="Required when purge policy requires backup checkpoint.")
        parser.add_argument("--allow-disabled", action="store_true", help="Allow disabled file organization profile.")

    def handle(self, *args, **options):
        source = _source(options["source_code"])
        if options["purge"]:
            metrics = purge_ready_source_files(
                source=source,
                backup_checkpoint_ref=options["backup_checkpoint_ref"],
                dry_run=options["dry_run"],
                require_enabled=not options["allow_disabled"],
            )
            self.stdout.write(
                self.style.SUCCESS(
                    "Memory file purge "
                    f"{'dry-run ' if options['dry_run'] else ''}finished for {source.code}: "
                    f"eligible={metrics['eligible']}, purged={metrics['purged']}, blocked={metrics['blocked']}"
                )
            )
            return
        metrics = run_move_worker(
            source=source,
            dry_run=options["dry_run"],
            limit=options["limit"],
            require_enabled=not options["allow_disabled"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Memory file move "
                f"{'dry-run ' if options['dry_run'] else ''}finished for {source.code}: "
                f"eligible={metrics['eligible']}, moved={metrics['moved']}, "
                f"needs_review={metrics['needs_review']}, failed={metrics['failed']}"
            )
        )


def _source(source_code: str):
    try:
        return MemorySource.objects.get(code=source_code)
    except MemorySource.DoesNotExist as exc:
        raise CommandError(f"MemorySource '{source_code}' does not exist.") from exc
