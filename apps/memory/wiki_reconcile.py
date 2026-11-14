"""Project committed OKF Notes, scoped to explicitly configured Git directories."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .knowledge_files import knowledge_repo_root, sha256_text
from .models import MemoryKnowledgeItem, WikiBundleCheckpoint
from .wiki_config import wiki_article_id, wiki_bundles

WIKI_SOURCE_KIND = "crow_note"
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class WikiInventoryError(ValidationError):
    """Safe diagnostic code only; Git/YAML diagnostics may reveal private names."""

    def __init__(self, code, *, conflicting_ids=()):
        super().__init__(code)
        self.conflicting_ids = tuple(conflicting_ids)


@dataclass(frozen=True)
class WikiNote:
    knowledge_id: str
    native_id: str
    path: str
    blob_oid: str
    file_hash: str
    metadata: dict
    body: str


@dataclass(frozen=True)
class WikiSnapshot:
    revision: str
    notes: dict[str, WikiNote]


def _git(root, *args):
    try:
        return subprocess.run(
            ["git", "--no-replace-objects", "--literal-pathspecs", *args],
            cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        raise WikiInventoryError("git_snapshot_unavailable") from None


def _valid_oid(value):
    if not isinstance(value, str) or not _OID.fullmatch(value):
        raise WikiInventoryError("invalid_git_object")
    return value


def wiki_head(root: Path) -> str:
    # Git otherwise searches parent directories when a configured mount is missing.
    if not (root / ".git").exists():
        raise WikiInventoryError("knowledge_repository_unavailable")
    return _valid_oid(_git(root, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip())


def wiki_tree(root: Path, revision: str, prefix: str) -> dict[str, str]:
    """All regular blobs under a confirmed tree, including non-reader material."""
    _valid_oid(revision)
    if _git(root, "cat-file", "-t", f"{revision}:{prefix}").strip() != b"tree":
        raise WikiInventoryError("bundle_not_a_tree")
    entries = {}
    for record in _git(root, "ls-tree", "-r", "-z", revision, "--", prefix).split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        mode, kind, oid = header.split()
        if mode not in (b"100644", b"100755") or kind != b"blob":
            continue
        try:
            path = raw_path.decode("utf-8")
        except UnicodeError:
            raise WikiInventoryError("invalid_git_path") from None
        if not path.startswith(prefix + "/"):
            raise WikiInventoryError("invalid_bundle_prefix")
        entries[path] = _valid_oid(oid.decode("ascii"))
    return entries


def wiki_blob(root: Path, oid: str) -> bytes:
    return _git(root, "cat-file", "blob", _valid_oid(oid))


def wiki_note_path(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    return (
        path.suffix.lower() == ".md"
        and path.name.lower() not in {"index.md", "log.md"}
        and not any(part.startswith(".") or part.lower() in {"raw", "schemas"} for part in path.parts)
    )


class _FrontmatterLoader(yaml.SafeLoader):
    # YAML's default silently discards duplicate keys, including id/status.
    def construct_mapping(self, node, deep=False):
        if isinstance(node, yaml.MappingNode):
            keys = [self.construct_object(key) for key, _ in node.value]
            if any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)):
                raise WikiInventoryError("invalid_frontmatter_keys")
        return super().construct_mapping(node, deep=deep)


def parse_wiki_frontmatter(raw: bytes) -> tuple[dict, str]:
    try:
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].rstrip("\r\n") != "---":
            raise WikiInventoryError("missing_frontmatter")
        end = next(i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---")
        meta = yaml.load("".join(lines[1:end]), Loader=_FrontmatterLoader)
        if not isinstance(meta, dict) or not isinstance(meta.get("type"), str):
            raise WikiInventoryError("invalid_frontmatter")
        return meta, "".join(lines[end + 1:]).strip()
    except (StopIteration, UnicodeError, yaml.YAMLError, RecursionError):
        raise WikiInventoryError("invalid_frontmatter") from None


def read_wiki_snapshot(bundle, revision: str | None = None) -> WikiSnapshot:
    root = knowledge_repo_root()
    revision = revision or wiki_head(root)
    tree = wiki_tree(root, revision, bundle.path)
    notes, native_ids = {}, set()
    for path, oid in tree.items():
        if not wiki_note_path(path[len(bundle.path) + 1:]):
            continue
        raw = wiki_blob(root, oid)
        meta, body = parse_wiki_frontmatter(raw)
        if meta["type"] != "Note":
            continue
        native = meta.get("id", "")
        if not isinstance(native, str) or native != native.strip():
            raise WikiInventoryError("invalid_native_id")
        try:
            knowledge_id = wiki_article_id(bundle, meta)
        except (ValueError, ValidationError):
            raise WikiInventoryError("invalid_note_id") from None
        if not knowledge_id or knowledge_id in notes or (native and native in native_ids):
            raise WikiInventoryError("missing_or_duplicate_note_id", conflicting_ids=[knowledge_id])
        if native:
            native_ids.add(native)
        notes[knowledge_id] = WikiNote(knowledge_id, native, path, oid, hashlib.sha256(raw).hexdigest(), meta, body)
    return WikiSnapshot(revision, notes)


def _policy_hash(bundle):
    # Re-check the configured policy even on the same Git revision.
    payload = [
        bundle.path, bundle.projection_user_id, sorted(bundle.read_tokens), sorted(bundle.write_tokens),
        bundle.note_read_tokens, bundle.sensitivity, bundle.model_context,
    ]
    return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def wiki_snapshot_ready(bundle, revision: str) -> bool:
    try:
        if wiki_head(knowledge_repo_root()) != revision:
            return False
    except WikiInventoryError:
        return False
    return WikiBundleCheckpoint.objects.filter(
        bundle_id=bundle.bundle_id, revision=revision, status="ready", policy_hash=_policy_hash(bundle),
    ).exists()


def registered_wiki_notes(bundle, revision):
    """Registration gate. The caller must still check actor and destination rights."""
    if not wiki_snapshot_ready(bundle, revision):
        return {}
    queryset = _bundle_items(bundle).filter(
        status=MemoryKnowledgeItem.Status.ACTIVE, knowledge_file_commit=revision, index_status="ready",
    )
    # A second bundle claiming an existing global ID must not expose either
    # version, even if the owner's own inventory completed successfully.
    denied = set()
    conflicts = WikiBundleCheckpoint.objects.filter(
        bundle_id__in=wiki_bundles(), status="error",
    ).exclude(conflicting_ids=[]).values_list("conflicting_ids", flat=True)
    for ids in conflicts:
        denied.update(ids)
    return {item.memory_id: item for item in queryset if item.memory_id not in denied}


def _bundle_items(bundle):
    return MemoryKnowledgeItem.objects.filter(source_kind=WIKI_SOURCE_KIND, metadata__wiki_bundle_id=bundle.bundle_id)


# The registry is the authority. A claim that might *narrow* the audience
# cannot simply be ignored and then exposed under the broader bundle policy.
_UNMAPPED_POLICY_FIELDS = {
    "access", "access_policy", "access_control", "acl", "audience", "classification",
    "confidentiality", "owner", "owner_user_id", "permissions", "privacy", "read_tokens",
    "roles", "scope", "scope_tokens", "security", "visibility", "write_tokens",
}


def _has_unmapped_policy(meta):
    contexts = [meta, meta.get("metadata"), meta.get("lbs")]
    for context in contexts:
        if not isinstance(context, dict):
            continue
        for key in context:
            normalized = key.casefold().replace("-", "_")
            if normalized in _UNMAPPED_POLICY_FIELDS or normalized.startswith(
                ("acl_", "privacy_", "access_", "audience_", "permission_", "scope_")
            ):
                return True
            if context is not meta and normalized == "sensitivity":
                return True
    return False


def _projected_values(bundle, snapshot, note, previous):
    meta = note.metadata
    status = meta.get("status", "stable")
    lifecycle = meta.get("lifecycle", "current")
    active = (
        status == "stable" and lifecycle == "current"
        and meta.get("sensitivity", bundle.sensitivity) == bundle.sensitivity
        and not _has_unmapped_policy(meta)
    )
    native_ids = set((previous.metadata if previous else {}).get("wiki_native_ids", []))
    if note.native_id:
        native_ids.add(note.native_id)
    # No confirmation authority is implied by an imported file or a service user's ID.
    confirmation = "needs_confirmation" if meta.get("confirmation_state") in ("confirmed", "needs_confirmation") else "working"
    return {
        "scope": MemoryKnowledgeItem.Scope.ORGANIZATION,
        "kind": MemoryKnowledgeItem.Kind.FACT,
        "sensitivity": bundle.sensitivity, "scope_tokens": [],
        "status": MemoryKnowledgeItem.Status.ACTIVE if active else MemoryKnowledgeItem.Status.QUARANTINED,
        "text_hash": sha256_text(note.body), "knowledge_file_hash": note.file_hash,
        "knowledge_file_path": note.path, "knowledge_file_commit": snapshot.revision,
        "source_kind": WIKI_SOURCE_KIND, "source_code": WIKI_SOURCE_KIND,
        "provenance": {"kind": "git_blob", "bundle_id": bundle.bundle_id, "blob_oid": note.blob_oid},
        "metadata": {
            "wiki_bundle_id": bundle.bundle_id, "wiki_native_ids": sorted(native_ids),
            "wiki_blob_oid": note.blob_oid, "okf_status": status if isinstance(status, str) else "invalid",
            "lifecycle": lifecycle if isinstance(lifecycle, str) else "invalid", "confirmation_state": confirmation,
        },
        "index_status": "ready" if active else "quarantined",
    }


def _apply(bundle, snapshot, *, force, dry_run, counts):
    items = {item.memory_id: item for item in _bundle_items(bundle)}
    alias_owner = {alias: item.memory_id for item in items.values()
                   for alias in item.metadata.get("wiki_native_ids", [])}
    new_ids = snapshot.notes.keys() - items.keys()
    conflicts = list(MemoryKnowledgeItem.objects.filter(memory_id__in=new_ids).values_list("memory_id", flat=True))
    if conflicts:
        raise WikiInventoryError("global_id_conflict", conflicting_ids=conflicts)
    for note in snapshot.notes.values():
        if note.native_id in alias_owner and alias_owner[note.native_id] != note.knowledge_id:
            raise WikiInventoryError("native_alias_conflict")
    for knowledge_id, note in snapshot.notes.items():
        item = items.get(knowledge_id)
        values = _projected_values(bundle, snapshot, note, item)
        if item is None:
            counts["created"] += 1
            if not dry_run:
                MemoryKnowledgeItem.objects.create(memory_id=knowledge_id, created_by_id=bundle.projection_user_id, **values)
        elif force or any(getattr(item, key) != val for key, val in values.items()):
            counts["moved" if item.knowledge_file_path != note.path else "updated"] += 1
            if not dry_run:
                for key, val in values.items():
                    setattr(item, key, val)
                item.save(update_fields=[*values, "updated_at"])
    missing = [item.pk for key, item in items.items() if key not in snapshot.notes and item.status != MemoryKnowledgeItem.Status.DELETED]
    counts["deleted"] = len(missing)
    if missing and not dry_run:
        MemoryKnowledgeItem.objects.filter(pk__in=missing).update(status=MemoryKnowledgeItem.Status.DELETED, index_status="deleted")


def reconcile_wiki_bundle(bundle, *, dry_run=False, force=False):
    """Apply all registered Notes and checkpoint together; never change the Git repo."""
    root = knowledge_repo_root()
    revision = ""
    counts = dict(created=0, updated=0, moved=0, deleted=0)
    with transaction.atomic():
        checkpoint = None
        if not dry_run:
            # Serialize workers for this bundle, including failure diagnostics.
            # A late failed worker must never replace a newer healthy checkpoint.
            checkpoint, _ = WikiBundleCheckpoint.objects.select_for_update().get_or_create(bundle_id=bundle.bundle_id)
        try:
            with transaction.atomic():
                revision = wiki_head(root)
                snapshot = read_wiki_snapshot(bundle, revision)
                if not get_user_model().objects.filter(pk=bundle.projection_user_id).exists():
                    raise WikiInventoryError("projection_user_missing")
                _apply(bundle, snapshot, force=force, dry_run=dry_run, counts=counts)
                if wiki_head(root) != revision:
                    raise WikiInventoryError("stale_revision")
        except (WikiInventoryError, IntegrityError) as exc:
            error = exc.messages[0] if isinstance(exc, WikiInventoryError) else "projection_integrity_error"
            ids = sorted(set(checkpoint.conflicting_ids if checkpoint else [])
                         | set(getattr(exc, "conflicting_ids", ())))
            if checkpoint and (checkpoint.status != "error" or checkpoint.error != error or checkpoint.conflicting_ids != ids):
                # The savepoint rolled back every partial projection above.
                # Keep the SHA of the last successful inventory for recovery.
                checkpoint.status, checkpoint.error, checkpoint.conflicting_ids = "error", error, ids
                checkpoint.save(update_fields=["status", "error", "conflicting_ids"])
            return dict(bundle_id=bundle.bundle_id, revision=revision, status="error", error=error,
                        created=0, updated=0, moved=0, deleted=0)
        if checkpoint:
            values = {"revision": revision, "policy_hash": _policy_hash(bundle), "status": "ready", "error": "",
                      "conflicting_ids": []}
            if any(getattr(checkpoint, key) != val for key, val in values.items()):
                WikiBundleCheckpoint.objects.filter(pk=checkpoint.pk).update(**values)
    return dict(bundle_id=bundle.bundle_id, revision=revision, status="ready", **counts)
