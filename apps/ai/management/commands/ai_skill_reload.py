from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ai.skills_service import clear_skill_catalog_cache, discover_skills


class Command(BaseCommand):
    help = "Clear the current process AI skill catalog cache and rediscover skills."

    def handle(self, *args, **options):
        clear_skill_catalog_cache()
        catalog = discover_skills(use_cache=False)
        self.stdout.write(self.style.SUCCESS(f"AI skill catalog reloaded in this process: {len(catalog)} skills."))
