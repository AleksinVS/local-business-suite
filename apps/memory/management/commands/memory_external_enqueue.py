import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.memory.external_connectors import enqueue_external_envelope, render_external_envelope_text, validate_external_envelope
from apps.memory.models import MemorySource
from apps.memory.security import scan_for_secrets


class Command(BaseCommand):
    help = "Write an external connector envelope to the landing zone and enqueue memory handoff."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", required=True, help="MemorySource code for the external connector.")
        parser.add_argument("--envelope-file", required=True, help="Path to a normalized external memory envelope JSON.")
        parser.add_argument("--raw-response-file", help="Optional raw API response JSON for short-lived quarantine mode.")
        parser.add_argument("--request-id", default="", help="Optional request/correlation id.")
        parser.add_argument("--priority", type=int, default=0, help="Queue priority; higher values run first.")
        parser.add_argument("--dry-run", action="store_true", help="Validate the request without writing landing zone or queue data.")

    def handle(self, *args, **options):
        try:
            source = MemorySource.objects.get(code=options["source_code"])
        except MemorySource.DoesNotExist as exc:
            raise CommandError(f"MemorySource '{options['source_code']}' does not exist. Run memory_sync_source first.") from exc

        envelope_path = Path(options["envelope_file"])
        if not envelope_path.exists():
            raise CommandError(f"Envelope file does not exist: {envelope_path}")
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))

        raw_response = None
        if options.get("raw_response_file"):
            raw_path = Path(options["raw_response_file"])
            if not raw_path.exists():
                raise CommandError(f"Raw response file does not exist: {raw_path}")
            raw_response = json.loads(raw_path.read_text(encoding="utf-8"))

        if options["dry_run"]:
            validate_external_envelope(envelope)
            if scan_for_secrets(render_external_envelope_text(envelope)).blocked:
                raise CommandError("Normalized external envelope contains credential material.")
            self.stdout.write(
                "External connector enqueue dry-run: "
                f"source={source.code}, envelope={envelope_path}, raw_response={'yes' if raw_response else 'no'}"
            )
            return

        job = enqueue_external_envelope(
            source=source,
            envelope=envelope,
            raw_response=raw_response,
            request_id=options["request_id"],
            priority=options["priority"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "External connector job queued: "
                f"job_id={job.job_id}, status={job.status}, source={job.source_code}"
            )
        )
