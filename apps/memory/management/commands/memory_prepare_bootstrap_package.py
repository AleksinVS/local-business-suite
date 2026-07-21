from django.core.management.base import BaseCommand, CommandError

from apps.memory.document_ingestion import prepare_bootstrap_package
from apps.memory.models import MemorySource


class Command(BaseCommand):
    help = "Prepare a safe/de-identified package for graph schema bootstrapping review."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", required=True, help="MemorySource code to package.")
        parser.add_argument("--department", required=True, help="Department/subdivision code or name.")
        parser.add_argument("--dry-run", action="store_true", help="Build package metadata without writing an artifact.")
        parser.add_argument("--limit", type=int, default=None, help="Optional maximum source objects to include.")

    def handle(self, *args, **options):
        try:
            source = MemorySource.objects.get(code=options["source_code"])
        except MemorySource.DoesNotExist as exc:
            raise CommandError(f"MemorySource '{options['source_code']}' does not exist. Run memory_sync_source first.") from exc

        package = prepare_bootstrap_package(
            source=source,
            department=options["department"],
            dry_run=options["dry_run"],
            limit=options["limit"],
        )
        suffix = f", path={package['path']}" if package.get("path") else ""
        self.stdout.write(
            self.style.SUCCESS(
                "Memory bootstrap package "
                f"{'dry-run ' if options['dry_run'] else ''}prepared: "
                f"source={source.code}, department={options['department']}, blocks={package['block_count']}{suffix}"
            )
        )
