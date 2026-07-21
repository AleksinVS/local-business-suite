# ADR-0030 decision 4 (packet 03): MemoryKnowledgeCandidate and
# MemoryReviewAction are removed in the schema migration that follows this one
# (0021). This data migration runs first so no data or in-flight review work
# is lost:
#
# - every row of both tables is archived to JSON under
#   ``<DATA_DIR>/memory/queue_archive/<table>.json`` (same best-effort,
#   read-only-filesystem-safe pattern as migration 0018's queue archive);
# - every still-OPEN candidate (status ``proposed``/``needs_review``) is
#   materialized as a real pending organization knowledge file + git commit,
#   via the same ``create_organization_candidate`` path the running
#   application uses, so an in-review candidate proposal is not silently
#   discarded by the schema change.
#
# Materializing a real knowledge file requires the concrete (non-historical)
# ``apps.memory`` model/service code -- ``MemoryKnowledgeItem`` is unaffected
# by this migration and by 0021, so importing it directly here (rather than
# via ``apps.get_model``) is safe and is the only practical way to reuse the
# real file-write + git-commit + reindex-skip-while-pending behavior instead
# of re-implementing it ad hoc inside a migration.
from __future__ import annotations

import json
import uuid
from pathlib import Path

from django.conf import settings
from django.db import migrations


def _archive_dir() -> Path:
    return Path(settings.DATA_DIR) / "memory" / "queue_archive"


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _row_to_dict(instance) -> dict:
    row = {}
    for field in instance._meta.fields:
        row[field.name] = _json_safe(field.value_from_object(instance))
    return row


def _dump_archive(*, name: str, rows: list[dict]) -> None:
    directory = _archive_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.json"
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        # Archival is best-effort: a read-only filesystem must not block the
        # schema migration that follows.
        pass


OPEN_CANDIDATE_STATUSES = {"proposed", "needs_review"}


def archive_and_materialize_candidates(apps, schema_editor):
    MemoryKnowledgeCandidate = apps.get_model("memory", "MemoryKnowledgeCandidate")
    MemoryReviewAction = apps.get_model("memory", "MemoryReviewAction")

    candidates = list(MemoryKnowledgeCandidate.objects.all().order_by("id"))
    review_actions = list(MemoryReviewAction.objects.all().order_by("id"))

    _dump_archive(name="memory_knowledge_candidate", rows=[_row_to_dict(row) for row in candidates])
    _dump_archive(name="memory_review_action", rows=[_row_to_dict(row) for row in review_actions])

    open_candidates = [row for row in candidates if row.status in OPEN_CANDIDATE_STATUSES]
    if not open_candidates:
        return

    # Real (non-historical) model/service imports: see module docstring.
    from apps.memory.chat_memory import create_organization_candidate
    from apps.memory.knowledge_files import write_knowledge_item_file
    from apps.memory.models import MemoryKnowledgeItem
    from django.contrib.auth import get_user_model

    User = get_user_model()

    for candidate in open_candidates:
        if candidate.source_item_id is not None:
            try:
                source_item = MemoryKnowledgeItem.objects.get(pk=candidate.source_item_id)
                creator = User.objects.get(pk=candidate.created_by_id)
            except (MemoryKnowledgeItem.DoesNotExist, User.DoesNotExist):
                continue
            create_organization_candidate(source_item=source_item, created_by=creator)
            continue

        # A freeform candidate with no linked personal source item: there is
        # no existing knowledge file to derive from, so materialize one
        # directly from the candidate's own proposed text.
        text = (candidate.proposed_text or "").strip()
        if not text:
            continue
        memory_id = f"legacy:candidate:{candidate.pk}"
        if MemoryKnowledgeItem.objects.filter(memory_id=memory_id).exists():
            continue
        item = MemoryKnowledgeItem.objects.create(
            memory_id=memory_id,
            scope=MemoryKnowledgeItem.Scope.ORGANIZATION,
            owner_user=None,
            kind=MemoryKnowledgeItem.Kind.FACT,
            text_hash="",
            sensitivity="internal",
            scope_tokens=["org:default"],
            status=MemoryKnowledgeItem.Status.ACTIVE,
            source_code="legacy_candidate_migration",
            source_kind="legacy_candidate_migration",
            index_status="indexing_pending",
            provenance={"legacy_candidate_id": candidate.pk},
            metadata={"lifecycle": "pending", "legacy_candidate_id": candidate.pk},
            created_by_id=candidate.created_by_id,
        )
        write_knowledge_item_file(
            item,
            body=text,
            commit_message=f"Migrate legacy organization candidate #{candidate.pk} to pending page",
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("memory", "0019_collapse_memory_queue_tables"),
    ]

    operations = [
        migrations.RunPython(archive_and_materialize_candidates, noop),
    ]
