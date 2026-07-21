"""Controlled `relations:` frontmatter validator and edge materializer.

ADR-0030 decision 3 (concept v0.5 §6, §7.3): the LLM graph-extraction contour
(``MemoryGraphEntity``/``MemoryGraphExtractionRun``/``MemoryGraphSchemaProposal``/
``MemoryGraphReviewItem``) is removed. Its replacement is this module:

* :func:`validate_relations_block` / :func:`validate_relation_entry` check a
  knowledge file's ``relations:`` frontmatter against the controlled edge-type
  vocabulary (``contracts/ai/memory_graph_schema.json``, loaded as
  ``settings.LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA``); an edge type not accepted
  in that contract is rejected with a clear error (the moderated-schema
  mechanic from ADR-0004, now carried by the contract + this validator instead
  of the removed proposal/review tables).
* :func:`materialize_knowledge_edges` walks every knowledge file, validates
  its declared edges, and (re)builds the :class:`~apps.memory.models.MemoryKnowledgeEdge`
  projection deterministically — no LLM. It is wired as a step of
  ``memory_reconcile`` and is idempotent: rebuilding from scratch with no file
  changes produces the same set of rows every time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from .knowledge_files import ensure_knowledge_repo, walk_all_knowledge_files
from .models import MemoryKnowledgeEdge


# Provenance must point at an immutable source (raw source, chat message,
# source object, ...), never at free prose describing the claim. The accepted
# shape is `kind:locator`, e.g. `source_code:relative/path`,
# `chat_session:<id>/message:<id>`, `source:<document_id>`.
_PROVENANCE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*:\S+$")
_WHITESPACE_PATTERN = re.compile(r"\s")


@dataclass(frozen=True)
class ValidatedRelation:
    edge_type: str
    target: str
    provenance: str


@dataclass(frozen=True)
class MaterializeResult:
    scanned_files: int
    scanned_relations: int
    created: int
    updated: int
    deleted: int
    skipped: list[dict]


def accepted_edge_types() -> dict[str, dict]:
    """Return the ``relation_types`` from the controlled vocabulary contract with ``status: accepted``.

    Backed by ``contracts/ai/memory_graph_schema.json``
    (``settings.LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA``, validated at settings
    load time by ``validate_memory_graph_schema_payload``). Only accepted
    entries are usable in ``relations:``; ``proposed``/``rejected``/``deprecated``
    entries exist in the contract for the moderated-schema expansion workflow
    but are not yet (or no longer) valid for authors to reference.
    """
    schema = getattr(settings, "LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA", {}) or {}
    relation_types = schema.get("relation_types") or {}
    return {
        code: item
        for code, item in relation_types.items()
        if isinstance(item, dict) and item.get("status") == "accepted"
    }


def validate_relation_entry(entry, *, index: int = 0) -> ValidatedRelation:
    """Validate a single ``relations:`` entry; raise ``ValidationError`` with a clear message."""
    if not isinstance(entry, dict):
        raise ValidationError(f"relations[{index}] должен быть объектом с полями type/target/provenance.")

    edge_type = str(entry.get("type") or "").strip()
    target = str(entry.get("target") or "").strip()
    provenance = str(entry.get("provenance") or "").strip()

    if not edge_type:
        raise ValidationError(f"relations[{index}] не содержит поле type.")
    vocabulary = accepted_edge_types()
    if edge_type not in vocabulary:
        allowed = ", ".join(sorted(vocabulary)) or "<нет принятых типов>"
        raise ValidationError(
            f"relations[{index}]: неизвестный или непринятый тип ребра '{edge_type}'. "
            f"Допустимые типы (contracts/ai/memory_graph_schema.json, relation_types со status=accepted): {allowed}."
        )

    if not target:
        raise ValidationError(f"relations[{index}] (type={edge_type}) не содержит поле target.")
    if _WHITESPACE_PATTERN.search(target):
        raise ValidationError(
            f"relations[{index}] (type={edge_type}): target '{target}' должен быть путем файла знания "
            "или knowledge_id (без пробелов), а не произвольным текстом."
        )

    if not provenance:
        raise ValidationError(f"relations[{index}] (type={edge_type}) не содержит поле provenance.")
    if not _PROVENANCE_PATTERN.match(provenance):
        raise ValidationError(
            f"relations[{index}] (type={edge_type}): provenance '{provenance}' должен указывать на "
            "immutable-источник в формате 'kind:locator' (например 'source_code:relative/path' или "
            "'chat_session:<id>/message:<id>'), а не быть произвольным текстом."
        )

    return ValidatedRelation(edge_type=edge_type, target=target, provenance=provenance)


def validate_relations_block(relations) -> list[ValidatedRelation]:
    """Validate a full ``relations:`` frontmatter list; raise on the first invalid entry.

    Returns an empty list for a missing/empty block (``relations:`` is
    optional). Intended for callers that want all-or-nothing validation (e.g.
    a direct write path); the materializer validates entries one at a time so
    a single bad relation does not block the rest of a file or repo.
    """
    if relations in (None, ""):
        return []
    if not isinstance(relations, list):
        raise ValidationError("relations: должен быть списком.")
    return [validate_relation_entry(entry, index=index) for index, entry in enumerate(relations)]


def _build_concept_index(entries: list[tuple[str, dict, str]]) -> dict[str, tuple[str, str]]:
    """Map every way a relation's ``target`` may reference a concept to ``(path, knowledge_id)``."""
    index: dict[str, tuple[str, str]] = {}
    for relative_path, meta, _body in entries:
        knowledge_id = str(meta.get("knowledge_id") or meta.get("legacy_memory_id") or "")
        record = (relative_path, knowledge_id)
        index[relative_path] = record
        if relative_path.endswith(".md"):
            index[relative_path[:-3]] = record
        if knowledge_id:
            index[knowledge_id] = record
    return index


def _resolve_target(target: str, concept_index: dict[str, tuple[str, str]]) -> tuple[str, str]:
    return concept_index.get(target, ("", ""))


def materialize_knowledge_edges(*, dry_run: bool = False, root: Path | None = None) -> MaterializeResult:
    """Rebuild ``MemoryKnowledgeEdge`` deterministically from every knowledge file's ``relations:`` block.

    No LLM: this is a plain parse-and-validate pass over the knowledge repo
    (the canon). Declared-but-unresolved targets (a concept referenced before
    its page exists) are tolerated — the row is still materialized with blank
    ``target_path``/``target_knowledge_id`` — matching the OKF permissive-link
    model (concept v0.5 §7.1: stale/broken links degrade gracefully rather
    than failing). An invalid relation entry (bad type/target/provenance
    shape) is skipped and reported in ``skipped`` rather than aborting the
    whole run, so one bad file cannot block reconciliation of the rest of the
    repo.

    Idempotent: run twice with no file changes in between and
    created/updated/deleted are all zero (the desired edge set — keyed by
    ``(source_path, edge_type, target)`` — is identical).
    """
    repo_root = root or ensure_knowledge_repo()
    entries = walk_all_knowledge_files(root=repo_root)
    concept_index = _build_concept_index(entries)

    desired: dict[tuple[str, str, str], dict] = {}
    skipped: list[dict] = []
    scanned_relations = 0

    for relative_path, meta, _body in entries:
        relations = meta.get("relations")
        if relations in (None, ""):
            continue
        if not isinstance(relations, list):
            skipped.append({"source_path": relative_path, "error": "relations: должен быть списком."})
            continue
        source_knowledge_id = str(meta.get("knowledge_id") or meta.get("legacy_memory_id") or "")
        for index, entry in enumerate(relations):
            scanned_relations += 1
            try:
                relation = validate_relation_entry(entry, index=index)
            except ValidationError as exc:
                skipped.append({"source_path": relative_path, "index": index, "error": str(exc)})
                continue
            target_path, target_knowledge_id = _resolve_target(relation.target, concept_index)
            key = (relative_path, relation.edge_type, relation.target)
            desired[key] = {
                "source_path": relative_path,
                "source_knowledge_id": source_knowledge_id,
                "edge_type": relation.edge_type,
                "target": relation.target,
                "target_path": target_path,
                "target_knowledge_id": target_knowledge_id,
                "provenance": relation.provenance,
            }

    existing = {
        (row.source_path, row.edge_type, row.target): row for row in MemoryKnowledgeEdge.objects.all()
    }

    to_create = [payload for key, payload in desired.items() if key not in existing]
    to_update = [
        (existing[key], payload)
        for key, payload in desired.items()
        if key in existing
        and (
            existing[key].source_knowledge_id != payload["source_knowledge_id"]
            or existing[key].target_path != payload["target_path"]
            or existing[key].target_knowledge_id != payload["target_knowledge_id"]
            or existing[key].provenance != payload["provenance"]
        )
    ]
    to_delete_keys = [key for key in existing if key not in desired]

    if dry_run:
        return MaterializeResult(
            scanned_files=len(entries),
            scanned_relations=scanned_relations,
            created=len(to_create),
            updated=len(to_update),
            deleted=len(to_delete_keys),
            skipped=skipped,
        )

    with transaction.atomic():
        if to_delete_keys:
            MemoryKnowledgeEdge.objects.filter(pk__in=[existing[key].pk for key in to_delete_keys]).delete()
        for row, payload in to_update:
            row.source_knowledge_id = payload["source_knowledge_id"]
            row.target_path = payload["target_path"]
            row.target_knowledge_id = payload["target_knowledge_id"]
            row.provenance = payload["provenance"]
            row.save(
                update_fields=[
                    "source_knowledge_id",
                    "target_path",
                    "target_knowledge_id",
                    "provenance",
                    "updated_at",
                ]
            )
        if to_create:
            MemoryKnowledgeEdge.objects.bulk_create(MemoryKnowledgeEdge(**payload) for payload in to_create)

    return MaterializeResult(
        scanned_files=len(entries),
        scanned_relations=scanned_relations,
        created=len(to_create),
        updated=len(to_update),
        deleted=len(to_delete_keys),
        skipped=skipped,
    )


__all__ = [
    "MaterializeResult",
    "ValidatedRelation",
    "accepted_edge_types",
    "materialize_knowledge_edges",
    "validate_relation_entry",
    "validate_relations_block",
]
