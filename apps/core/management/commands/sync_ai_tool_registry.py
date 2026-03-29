import json

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ai.tool_definitions import get_registry_payload


class Command(BaseCommand):
    help = "Generate config/ai/tools.json from canonical Python tool definitions."

    def handle(self, *args, **options):
        payload = get_registry_payload()
        output_path = settings.LOCAL_BUSINESS_AI_TOOLS_FILE
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Generated {output_path}"))