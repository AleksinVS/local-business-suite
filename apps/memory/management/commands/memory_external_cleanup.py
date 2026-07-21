from django.core.management.base import BaseCommand

from apps.memory.external_connectors import clean_external_connector_artifacts


class Command(BaseCommand):
    help = "Report or remove expired external connector landing-zone artifacts."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", help="Limit cleanup to one MemorySource code.")
        parser.add_argument("--dry-run", action="store_true", help="Report expired artifacts without deleting them.")
        parser.add_argument("--yes", action="store_true", help="Confirm deletion in real cleanup mode.")

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"] or not options["yes"])
        entries = clean_external_connector_artifacts(
            source_code=options.get("source_code"),
            dry_run=dry_run,
        )
        mode = "dry-run" if dry_run else "delete"
        self.stdout.write(f"External connector cleanup {mode}: expired={len(entries)}")
        for entry in entries:
            action = "removed" if entry.removed else "would_remove"
            self.stdout.write(
                f"{action} kind={entry.artifact_kind} retention_days={entry.retention_days} path={entry.path}"
            )
        if not options["dry_run"] and not options["yes"]:
            self.stdout.write("No files were deleted. Pass --yes to run real cleanup.")
