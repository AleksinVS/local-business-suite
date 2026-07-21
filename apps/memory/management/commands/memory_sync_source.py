from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.memory.models import MemorySource
from apps.memory.services import sync_sources_from_contract


SOURCE_FIELD_DEFAULTS = {
    "title": "title",
    "source_kind": "source_kind",
    "domain": "domain",
    "owner": "owner",
    "sync_mode": "sync_mode",
    "scope_rule": "scope_rule",
    "sensitivity": "sensitivity",
    "pii_policy": "pii_policy",
    "extractor_profile": "extractor_profile",
    "chunking_profile": "chunking_profile",
    "index_profiles": "index_profiles",
}


class Command(BaseCommand):
    help = "Synchronize MemorySource rows from settings.LOCAL_BUSINESS_MEMORY_SOURCES."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-code",
            help="Synchronize only one source code from the configured memory source contract.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned MemorySource changes without writing to the database.",
        )

    def handle(self, *args, **options):
        sources_payload = list(getattr(settings, "LOCAL_BUSINESS_MEMORY_SOURCES", []) or [])
        source_code = (options.get("source_code") or "").strip()
        dry_run = bool(options.get("dry_run"))

        if source_code:
            sources_payload = [item for item in sources_payload if item.get("code") == source_code]
            if not sources_payload:
                raise CommandError(f"Memory source '{source_code}' is not defined in settings.LOCAL_BUSINESS_MEMORY_SOURCES.")

        if dry_run:
            summary = self._dry_run_summary(sources_payload)
            self.stdout.write(
                "MemorySource dry-run: "
                f"create={summary['create']}, update={summary['update']}, unchanged={summary['unchanged']}"
            )
            for item in summary["items"]:
                self.stdout.write(f"  {item['code']}: {item['action']}")
            return

        synced_sources = sync_sources_from_contract(sources_payload)
        self.stdout.write(self.style.SUCCESS(f"MemorySource synchronized: {len(synced_sources)}"))

    def _dry_run_summary(self, sources_payload):
        summary = {"create": 0, "update": 0, "unchanged": 0, "items": []}
        existing_by_code = {
            source.code: source
            for source in MemorySource.objects.filter(code__in=[item["code"] for item in sources_payload])
        }

        for item in sources_payload:
            source = existing_by_code.get(item["code"])
            if source is None:
                action = "create"
            elif _source_has_changes(source, item):
                action = "update"
            else:
                action = "unchanged"
            summary[action] += 1
            summary["items"].append({"code": item["code"], "action": action})
        return summary


def _source_has_changes(source, item):
    expected_status = MemorySource.Status.ENABLED if item.get("enabled", True) else MemorySource.Status.DISABLED
    if source.status != expected_status:
        return True
    if source.config != item:
        return True
    for model_field, payload_field in SOURCE_FIELD_DEFAULTS.items():
        expected = item.get(payload_field, "" if model_field != "index_profiles" else [])
        if getattr(source, model_field) != expected:
            return True
    return False
