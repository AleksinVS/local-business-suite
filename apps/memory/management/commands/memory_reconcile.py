"""Pull reconciler for the knowledge file canon (ADR-0030 decision 2).

The knowledge markdown file is the canon; the database projection
(``MemoryKnowledgeItem`` + search documents) is rebuildable. This command
compares each knowledge file with its projection using a content-hash gate and
rebuilds only the drifted projections. It is idempotent (a second run with no
changes reports zero reconciled) and self-healing (a manual edit is picked up
without breaking reads).

Guardrail: a manual edit may not silently lower a page's classification
(``sensitivity``). A downgrade is held pending an explicit review; the old,
higher classification stays in force. Automatic label movement is upward only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.memory.chat_memory import index_knowledge_item
from apps.memory.knowledge_edges import materialize_knowledge_edges
from apps.memory.knowledge_files import (
    _git_head,
    _safe_repo_path,
    knowledge_repo_root,
    parse_knowledge_file,
    rebuild_all_knowledge_indexes,
    rebuild_all_knowledge_logs,
    sha256_text,
)
from apps.memory.models import MemoryKnowledgeItem
from apps.memory.routing import FALLBACK_SENSITIVITY_LEVELS


def _reconcile_state_path() -> Path:
    return Path(settings.DATA_DIR) / "memory" / "reconcile_state.json"


def _load_state() -> dict:
    path = _reconcile_state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (ValueError, OSError):
        return {}


def _save_state(state: dict) -> None:
    path = _reconcile_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _sensitivity_rank(value: str) -> int:
    try:
        return FALLBACK_SENSITIVITY_LEVELS.index((value or "").strip())
    except ValueError:
        return -1


def _is_downgrade(file_sensitivity: str, current_sensitivity: str) -> bool:
    file_rank = _sensitivity_rank(file_sensitivity)
    current_rank = _sensitivity_rank(current_sensitivity)
    return file_rank >= 0 and current_rank >= 0 and file_rank < current_rank


class Command(BaseCommand):
    help = "Rebuild memory projections from the knowledge file canon (ADR-0030)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report drift without writing projections or state.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Reindex every knowledge file even if the content hash matches.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        force = bool(options.get("force"))
        root = knowledge_repo_root()
        head = _git_head(root) if (root / ".git").exists() else ""

        items = MemoryKnowledgeItem.objects.exclude(knowledge_file_path="").filter(
            status=MemoryKnowledgeItem.Status.ACTIVE
        )
        scanned = 0
        reconciled = 0
        held = 0
        for item in items.iterator():
            scanned += 1
            path = _safe_repo_path(root, item.knowledge_file_path)
            if not path.exists():
                continue
            raw_content = path.read_text(encoding="utf-8")
            parsed = parse_knowledge_file(raw_content)
            meta = parsed.metadata or {}
            body_hash = sha256_text(parsed.body)

            file_sensitivity = str(meta.get("sensitivity") or item.sensitivity)
            file_scope_tokens = [str(t) for t in (meta.get("scope_tokens") or [])]
            file_status = str(meta.get("status") or item.status)
            file_kind = str(meta.get("kind") or item.kind)

            content_changed = body_hash != item.text_hash
            metadata_changed = (
                file_sensitivity != item.sensitivity
                or file_scope_tokens != [str(t) for t in (item.scope_tokens or [])]
                or file_status != item.status
                or file_kind != item.kind
            )
            if not (content_changed or metadata_changed) and not force:
                continue

            # Classification guard: no silent downgrade of sensitivity via a
            # manual edit. Hold the page pending an explicit review and keep the
            # existing (higher) classification in force.
            if _is_downgrade(file_sensitivity, item.sensitivity) or _is_downgrade(
                _lowest(file_scope_tokens), _lowest([str(t) for t in (item.scope_tokens or [])])
            ):
                held += 1
                self.stdout.write(f"held (classification downgrade pending review): {item.memory_id}")
                if not dry_run:
                    md = dict(item.metadata or {})
                    md["lifecycle"] = "pending"
                    md["pending_reason"] = "classification_downgrade"
                    item.metadata = md
                    item.save(update_fields=["metadata", "updated_at"])
                continue

            reconciled += 1
            if dry_run:
                self.stdout.write(f"would reconcile: {item.memory_id}")
                continue

            # Apply the authoritative frontmatter to the projection (upward only
            # for classification, already guarded above) and rebuild indexes.
            item.text_hash = body_hash
            item.knowledge_file_hash = sha256_text(raw_content)
            item.sensitivity = file_sensitivity
            item.scope_tokens = file_scope_tokens or list(item.scope_tokens or [])
            item.status = file_status
            item.kind = file_kind
            md = dict(item.metadata or {})
            md["lifecycle"] = str(meta.get("lifecycle") or "current")
            item.metadata = md
            item.save(
                update_fields=[
                    "text_hash",
                    "knowledge_file_hash",
                    "sensitivity",
                    "scope_tokens",
                    "status",
                    "kind",
                    "metadata",
                    "updated_at",
                ]
            )
            if item.status == MemoryKnowledgeItem.Status.ACTIVE:
                index_knowledge_item(item)

        # DEBT(ADR-0030-5a): dataset registry materialization from `type: Dataset`
        # concept pages will be added here in stage 5a (data store), building the
        # dataset registry projection from the wiki, like edges from `relations:`.

        # ADR-0030 decision 3: the graph-extraction contour is replaced by a
        # deterministic materializer that parses every knowledge file's
        # `relations:` frontmatter against the controlled edge-type vocabulary
        # (contracts/ai/memory_graph_schema.json) and (re)builds
        # MemoryKnowledgeEdge. No LLM; runs on every reconcile (like the
        # index/log rebuild below), not gated by the per-item content-hash
        # loop above, since edges depend on the whole corpus (a target may
        # live in an unrelated file). `--dry-run` reports the projected
        # create/update/delete counts without writing.
        edges_result = materialize_knowledge_edges(dry_run=dry_run)

        indexes_written = []
        logs_written = []
        if not dry_run:
            # ADR-0030 decision 4: index.md is generated from the knowledge
            # files on disk (not the DB queryset); rebuild it here so a batch
            # of reconciled files is reflected immediately. log.md is
            # generated from git log the same way, right after, since it is
            # never hand-edited either.
            indexes_written = rebuild_all_knowledge_indexes()
            logs_written = rebuild_all_knowledge_logs()
            state = _load_state()
            state["last_commit"] = head
            state["reconciled_at"] = timezone.now().isoformat()
            _save_state(state)

        self.stdout.write(
            "Memory reconcile finished: "
            f"scanned={scanned}, reconciled={reconciled}, held={held}, "
            f"indexes_written={len(indexes_written)}, logs_written={len(logs_written)}, "
            f"edges_created={edges_result.created}, edges_updated={edges_result.updated}, "
            f"edges_deleted={edges_result.deleted}, edges_skipped={len(edges_result.skipped)}, "
            f"dry_run={dry_run}, head={head[:12] or 'none'}"
        )


def _lowest(tokens: list[str]) -> str:
    """Return the least-sensitive known token to compare scope_token ladders.

    scope_tokens are free-form, but any that name a known sensitivity level are
    subject to the same no-downgrade rule; unknown tokens rank -1 and are
    ignored by the guard.
    """
    ranked = [(_sensitivity_rank(t), t) for t in tokens]
    known = [pair for pair in ranked if pair[0] >= 0]
    if not known:
        return ""
    return min(known)[1]
