from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.json_utils import (
    load_json_file,
    pretty_json,
    validate_task_brief_payload,
)


class Command(BaseCommand):
    help = "Generate a machine-readable change plan skeleton from a task brief JSON."

    def add_arguments(self, parser):
        parser.add_argument("brief_path", type=str)
        parser.add_argument("--output", type=str)

    def handle(self, *args, **options):
        brief_path = Path(options["brief_path"])
        if not brief_path.exists():
            raise CommandError(f"Task brief file not found: {brief_path}")

        brief = load_json_file(brief_path)
        validate_task_brief_payload(brief)

        plan = {
            "brief_id": brief["id"],
            "title": brief["title"],
            "status": "draft",
            "summary": brief["objective"],
            "assumptions": [],
            "affected_files": [],
            "steps": [
                {
                    "id": "step-1",
                    "title": "Inspect current implementation",
                    "status": "pending",
                    "notes": "",
                },
                {
                    "id": "step-2",
                    "title": "Implement requested changes",
                    "status": "pending",
                    "notes": "",
                },
                {
                    "id": "step-3",
                    "title": "Verify and document outcome",
                    "status": "pending",
                    "notes": "",
                },
            ],
            "verification": [{"type": "tests", "command": "./.venv/bin/python manage.py test"}],
            "risks": [],
        }

        output = pretty_json(plan) + "\n"
        output_path = options.get("output")
        if output_path:
            Path(output_path).write_text(output, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Change plan written to {output_path}"))
            return
        self.stdout.write(output)

