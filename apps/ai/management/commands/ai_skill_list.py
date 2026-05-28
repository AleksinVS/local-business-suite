from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ai.skills_service import discover_skills


class Command(BaseCommand):
    help = "List available AI skills from module registry and contract files."

    def handle(self, *args, **options):
        for item in discover_skills(use_cache=False):
            self.stdout.write(
                f"{item['id']}\t{item.get('registration_source', '')}\t{item.get('description', '')}"
            )
