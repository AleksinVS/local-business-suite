import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Delete expired temporary memory processing files from raw/safe/extraction zones."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show planned cleanup without deleting files.")
        parser.add_argument("--retention-days", type=int, default=None, help="Override retention in days.")

    def handle(self, *args, **options):
        root = Path(os.environ.get("LOCAL_BUSINESS_PROCESSING_DIR", "") or Path(settings.DATA_DIR) / "processing")
        retention_days = (
            int(options["retention_days"])
            if options["retention_days"] is not None
            else int(settings.LOCAL_BUSINESS_PROCESSING_RETENTION_DAYS)
        )
        cutoff = timezone.now().timestamp() - retention_days * 24 * 60 * 60
        planned = []
        for name in ("raw_quarantine", "safe_work", "extraction_packets"):
            directory = root / name
            directory.mkdir(parents=True, exist_ok=True)
            for path in directory.rglob("*"):
                if path.is_file() and path.stat().st_mtime < cutoff:
                    planned.append(path)

        if options["dry_run"]:
            self.stdout.write(f"Processing cleanup dry-run: expired_files={len(planned)}, retention_days={retention_days}")
            return

        deleted = 0
        for path in planned:
            path.unlink(missing_ok=True)
            deleted += 1
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} expired processing file(s)."))
