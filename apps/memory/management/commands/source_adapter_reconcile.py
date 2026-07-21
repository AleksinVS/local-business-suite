from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.analytics.services import delete_analytics_projection_from_envelope, upsert_analytics_projection_from_envelope
from apps.core.source_adapters import OPERATION_DELETE, SourceObjectEnvelope, get_source_adapter, registered_source_adapters
from apps.memory.models import MemorySource, MemorySourceObject
from apps.memory.services import delete_memory_projection_from_envelope, upsert_memory_projection_from_envelope


class Command(BaseCommand):
    help = "Reconcile universal source adapter envelopes into memory and analytics projections."

    def add_arguments(self, parser):
        parser.add_argument("--source-code", help="Limit reconcile to one registered source adapter.")
        parser.add_argument(
            "--target",
            choices=("memory", "analytics", "all"),
            default="all",
            help="Projection target to refresh.",
        )
        parser.add_argument(
            "--backend",
            choices=("fulltext", "vector", "all"),
            default="all",
            help="Memory index backend to rebuild.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Inspect changes without writing projections.")

    def handle(self, *args, **options):
        source_code = (options.get("source_code") or "").strip()
        target = options["target"]
        dry_run = bool(options.get("dry_run"))
        backend = options["backend"]
        index_backends = ("fulltext", "vector") if backend == "all" else (backend,)

        adapters = registered_source_adapters()
        if source_code:
            adapter = get_source_adapter(source_code)
            if adapter is None:
                self._mark_missing_adapter(source_code, dry_run=dry_run)
                raise CommandError(f"Source adapter '{source_code}' is not registered.")
            adapters = {source_code: adapter}
        if not adapters:
            raise CommandError("No source adapters are registered.")

        total = {
            "sources": 0,
            "seen": 0,
            "memory_upserted": 0,
            "analytics_upserted": 0,
            "deleted": 0,
            "blocked": 0,
            "failed": 0,
            "dry_run": dry_run,
        }
        for adapter_code, adapter in adapters.items():
            result = self._reconcile_adapter(
                adapter_code=adapter_code,
                adapter=adapter,
                target=target,
                index_backends=index_backends,
                dry_run=dry_run,
            )
            total["sources"] += 1
            for key in ("seen", "memory_upserted", "analytics_upserted", "deleted", "blocked", "failed"):
                total[key] += result[key]

        self.stdout.write(
            "Source adapter reconcile: "
            f"sources={total['sources']} seen={total['seen']} "
            f"memory_upserted={total['memory_upserted']} analytics_upserted={total['analytics_upserted']} "
            f"deleted={total['deleted']} blocked={total['blocked']} failed={total['failed']} "
            f"dry_run={total['dry_run']}"
        )

    def _reconcile_adapter(self, *, adapter_code, adapter, target, index_backends, dry_run):
        result = {
            "seen": 0,
            "memory_upserted": 0,
            "analytics_upserted": 0,
            "deleted": 0,
            "blocked": 0,
            "failed": 0,
        }
        seen_object_ids = set()
        for source_object in adapter.iter_changed_objects({}):
            try:
                envelope = adapter.render_envelope(source_object)
                seen_object_ids.add(envelope.object_id)
                result["seen"] += 1
                if target in {"memory", "all"}:
                    memory_result = upsert_memory_projection_from_envelope(
                        envelope,
                        index_backends=index_backends,
                        dry_run=dry_run,
                    )
                    if memory_result.get("blocked"):
                        result["blocked"] += 1
                    else:
                        result["memory_upserted"] += 1
                if target in {"analytics", "all"}:
                    analytics_result = upsert_analytics_projection_from_envelope(
                        envelope,
                        facts=list(adapter.extract_analytics_facts(envelope)),
                        dry_run=dry_run,
                    )
                    result["analytics_upserted"] += 1 if not analytics_result.get("dry_run") or dry_run else 0
            except Exception as exc:
                result["failed"] += 1
                self.stderr.write(f"{adapter_code}: failed to reconcile object: {exc}")

        if target in {"memory", "all"}:
            result["deleted"] += self._delete_missing_memory_objects(
                adapter_code=adapter_code,
                seen_object_ids=seen_object_ids,
                index_backends=index_backends,
                target=target,
                dry_run=dry_run,
            )
        return result

    def _delete_missing_memory_objects(self, *, adapter_code, seen_object_ids, index_backends, target, dry_run):
        source = MemorySource.objects.filter(code=adapter_code).first()
        if source is None:
            return 0
        queryset = MemorySourceObject.objects.filter(source=source).exclude(object_id__in=seen_object_ids)
        count = queryset.count()
        if dry_run or count == 0:
            return count
        for source_object in queryset:
            envelope = SourceObjectEnvelope(
                source_code=source.code,
                source_origin=(source.config or {}).get("source_origin", "internal"),
                source_kind=source.source_kind,
                domain=source.domain,
                object_type=(source_object.metadata or {}).get("object_type", "source_object"),
                object_id=source_object.object_id,
                operation=OPERATION_DELETE,
                title=source_object.file_name or source_object.object_id,
                text="",
                content_hash=source_object.content_hash or "deleted",
                source_updated_at=timezone.now(),
                sensitivity=source.sensitivity,
                privacy_profile=(source_object.metadata or {}).get("privacy_profile", "pii_off"),
                access_policy=(source_object.metadata or {}).get("access_policy", {}),
            )
            delete_memory_projection_from_envelope(envelope, index_backends=index_backends, dry_run=False)
            if target == "all":
                delete_analytics_projection_from_envelope(envelope, dry_run=False)
        return count

    def _mark_missing_adapter(self, source_code, *, dry_run):
        if dry_run:
            return
        MemorySource.objects.filter(code=source_code).update(
            status=MemorySource.Status.MISSING_ADAPTER,
            error_message="Source adapter is not registered; adapter_check results fail closed.",
        )
