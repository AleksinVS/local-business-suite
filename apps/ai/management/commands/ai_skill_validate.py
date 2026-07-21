from __future__ import annotations

from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.ai.skill_authoring import list_runtime_skill_files, validate_runtime_skill_file
from apps.ai.skills_service import discover_skills


class Command(BaseCommand):
    help = "Validate AI skill metadata and runtime SKILL.md files."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Validate catalog discovery and all runtime skill files.")
        parser.add_argument("--path", default="", help="Validate one runtime SKILL.md file.")

    def handle(self, *args, **options):
        try:
            if options.get("path"):
                entry = validate_runtime_skill_file(Path(options["path"]))
                self.stdout.write(self.style.SUCCESS(f"Valid skill: {entry['id']}"))
                return
            if options.get("all"):
                catalog = discover_skills(use_cache=False)
                for path in list_runtime_skill_files():
                    validate_runtime_skill_file(path)
                self.stdout.write(self.style.SUCCESS(f"AI skills are valid: {len(catalog)} discovered."))
                return
        except ValidationError as exc:
            raise CommandError(str(exc)) from exc
        raise CommandError("Use --all or --path <SKILL.md>.")
