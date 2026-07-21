import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.core.performance import summarize_performance_events


class Command(BaseCommand):
    help = "Report p50/p95 latency from local performance JSONL events."

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            dest="input_path",
            default="",
            help="Path to performance_events.jsonl. Defaults to LOCAL_BUSINESS_PERFORMANCE_METRICS_PATH.",
        )
        parser.add_argument(
            "--group-by",
            choices=["route_name", "route_pattern", "event_type", "status_code", "none"],
            default="route_name",
            help="Field used for grouping latency rows.",
        )
        parser.add_argument(
            "--event-type",
            default="http_request",
            help="Event type to include. Use an empty value to include all event types.",
        )
        parser.add_argument("--min-count", type=int, default=1, help="Minimum events required for a group.")
        parser.add_argument("--top", type=int, default=20, help="Maximum number of rows to show.")
        parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    def handle(self, *args, **options):
        input_path = Path(options["input_path"]) if options["input_path"] else None
        rows = summarize_performance_events(
            input_path,
            event_type=options["event_type"],
            group_by=options["group_by"],
            min_count=options["min_count"],
            top=options["top"],
        )
        if options["json"]:
            self.stdout.write(json.dumps(rows, ensure_ascii=False, indent=2))
            return
        if not rows:
            self.stdout.write("No performance events found.")
            return
        self.stdout.write("group | count | p50_ms | p95_ms | max_ms | status_codes")
        for row in rows:
            self.stdout.write(
                "{group} | {count} | {p50_ms} | {p95_ms} | {max_ms} | {status_codes}".format(**row)
            )
