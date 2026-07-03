from __future__ import annotations

import contextlib
import hashlib
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from .models import MemoryKnowledgeItem
from .policies import can_access_knowledge_item


FRONT_MATTER_SEPARATOR = "---"
SUMMARY_FILE_NAME = "_summary.md"


@dataclass(frozen=True)
class KnowledgeFile:
    metadata: dict[str, Any]
    body: str


@dataclass(frozen=True)
class KnowledgeFileWriteResult:
    relative_path: str
    absolute_path: Path
    text_hash: str
    file_hash: str
    commit_hash: str


def knowledge_repo_root() -> Path:
    override = os.environ.get("LOCAL_BUSINESS_KNOWLEDGE_REPO_DIR", "").strip()
    if override:
        return Path(override)
    return Path(settings.DATA_DIR) / "knowledge_repo"


def ensure_knowledge_repo() -> Path:
    root = knowledge_repo_root()
    root.mkdir(parents=True, exist_ok=True)
    _write_schema_file(root)
    if not (root / ".git").exists():
        _run_git(root, "init")
    _ensure_git_identity(root)
    return root


def build_knowledge_file_relative_path(item: MemoryKnowledgeItem) -> str:
    if item.knowledge_file_path:
        return item.knowledge_file_path
    year = (item.created_at or timezone.now()).year
    source_code = _safe_path_part(item.source_code or "chat")
    file_name = f"{_safe_file_stem(item.memory_id)}.md"
    if item.scope == MemoryKnowledgeItem.Scope.ORGANIZATION:
        return f"org/sources/{source_code}/{year}/{file_name}"
    if not item.owner_user_id:
        raise ValidationError("Personal knowledge item must have owner_user_id for file path.")
    return f"users/{item.owner_user_id}/sources/{source_code}/{year}/{file_name}"


def write_knowledge_item_file(
    item: MemoryKnowledgeItem,
    *,
    body: str,
    commit_message: str = "",
) -> KnowledgeFileWriteResult:
    body = (body or "").strip()
    if not body:
        raise ValidationError("Knowledge file body must not be empty.")
    root = ensure_knowledge_repo()
    relative_path = build_knowledge_file_relative_path(item)
    target = _safe_repo_path(root, relative_path)
    payload = KnowledgeFile(metadata=_knowledge_file_metadata(item, body=body), body=body)
    content = render_knowledge_file(payload)
    text_hash = sha256_text(body)
    file_hash = sha256_text(content)

    with knowledge_repo_lock(root):
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_name(target.name + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        if sha256_text(tmp_path.read_text(encoding="utf-8")) != file_hash:
            tmp_path.unlink(missing_ok=True)
            raise ValidationError("Knowledge file hash check failed before replace.")
        os.replace(tmp_path, target)
        _run_git(root, "add", relative_path)
        if (root / "schemas" / "knowledge_file.schema.json").exists():
            _run_git(root, "add", "schemas/knowledge_file.schema.json")
        _commit_if_needed(root, commit_message or f"Update knowledge {item.memory_id}")
        commit_hash = _git_head(root)

    item.knowledge_file_path = relative_path
    item.knowledge_file_hash = file_hash
    item.knowledge_file_commit = commit_hash
    item.text_hash = text_hash
    item.save(
        update_fields=[
            "knowledge_file_path",
            "knowledge_file_hash",
            "knowledge_file_commit",
            "text_hash",
            "updated_at",
        ]
    )
    return KnowledgeFileWriteResult(
        relative_path=relative_path,
        absolute_path=target,
        text_hash=text_hash,
        file_hash=file_hash,
        commit_hash=commit_hash,
    )


def read_knowledge_item_file(item: MemoryKnowledgeItem) -> KnowledgeFile:
    if not item.knowledge_file_path:
        raise ValidationError(f"Knowledge item {item.memory_id} has no knowledge file path.")
    root = knowledge_repo_root()
    path = _safe_repo_path(root, item.knowledge_file_path)
    if not path.exists():
        raise ValidationError(f"Knowledge file for {item.memory_id} is missing.")
    content = path.read_text(encoding="utf-8")
    if item.knowledge_file_hash and sha256_text(content) != item.knowledge_file_hash:
        raise ValidationError(f"Knowledge file hash mismatch for {item.memory_id}.")
    parsed = parse_knowledge_file(content)
    if sha256_text(parsed.body) != item.text_hash:
        raise ValidationError(f"Knowledge body hash mismatch for {item.memory_id}.")
    return parsed


def read_knowledge_for_actor(*, item: MemoryKnowledgeItem, actor, request_id: str = "") -> dict[str, Any]:
    if not can_access_knowledge_item(actor, item):
        raise PermissionDenied("Knowledge item is not available for this user.")
    parsed = read_knowledge_item_file(item)
    return {
        "result_type": "knowledge",
        "knowledge_id": item.memory_id,
        "text": parsed.body,
        "source_refs": parsed.metadata.get("source_refs") or item.source_refs,
        "source_kind": parsed.metadata.get("source_kind") or item.source_kind,
        "source_code": parsed.metadata.get("source_code") or item.source_code,
        "scope": parsed.metadata.get("scope") or item.scope,
        "index_status": item.index_status,
        "knowledge_file_path": item.knowledge_file_path,
        "request_id": request_id,
    }


def verify_knowledge_item_file(item: MemoryKnowledgeItem) -> dict[str, Any]:
    parsed = None
    text_hash = ""
    file_hash = ""
    file_exists = False
    error = ""
    if item.knowledge_file_path:
        path = _safe_repo_path(knowledge_repo_root(), item.knowledge_file_path)
        file_exists = path.exists()
        if file_exists:
            content = path.read_text(encoding="utf-8")
            file_hash = sha256_text(content)
            try:
                parsed = parse_knowledge_file(content)
                text_hash = sha256_text(parsed.body)
            except Exception as exc:
                error = str(exc)
    return {
        "memory_id": item.memory_id,
        "file_exists": file_exists,
        "text_hash": text_hash,
        "metadata_text_hash": item.text_hash,
        "file_hash": file_hash,
        "metadata_file_hash": item.knowledge_file_hash,
        "error": error,
        "ok": bool(item.knowledge_file_path)
        and file_exists
        and text_hash == item.text_hash
        and (not item.knowledge_file_hash or file_hash == item.knowledge_file_hash),
    }


def rebuild_knowledge_summaries(*, scope: str, owner_user=None) -> list[str]:
    root = ensure_knowledge_repo()
    queryset = MemoryKnowledgeItem.objects.filter(scope=scope, status=MemoryKnowledgeItem.Status.ACTIVE)
    if scope == MemoryKnowledgeItem.Scope.PERSONAL:
        if owner_user is None:
            raise ValidationError("owner_user is required for personal summary.")
        queryset = queryset.filter(owner_user=owner_user)
        summary_paths = [f"users/{owner_user.id}/{SUMMARY_FILE_NAME}"]
    else:
        queryset = queryset.filter(owner_user__isnull=True)
        summary_paths = [f"org/{SUMMARY_FILE_NAME}"]

    items = list(queryset.order_by("source_code", "created_at", "id"))
    content = _summary_markdown(scope=scope, owner_user=owner_user, items=items)
    written = []
    with knowledge_repo_lock(root):
        for relative_path in summary_paths:
            path = _safe_repo_path(root, relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_name(path.name + ".tmp")
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(tmp_path, path)
            _run_git(root, "add", relative_path)
            written.append(relative_path)
        _commit_if_needed(root, f"Update {scope} knowledge summary")
    return written


def render_knowledge_file(payload: KnowledgeFile) -> str:
    metadata = yaml.safe_dump(_plain_value(payload.metadata), allow_unicode=True, sort_keys=False).strip()
    body = (payload.body or "").strip()
    return f"{FRONT_MATTER_SEPARATOR}\n{metadata}\n{FRONT_MATTER_SEPARATOR}\n\n{body}\n"


def parse_knowledge_file(content: str) -> KnowledgeFile:
    if not content.startswith(FRONT_MATTER_SEPARATOR + "\n"):
        return KnowledgeFile(metadata={}, body=content.strip())
    _, rest = content.split(FRONT_MATTER_SEPARATOR + "\n", 1)
    metadata_text, body = rest.split("\n" + FRONT_MATTER_SEPARATOR, 1)
    metadata = yaml.safe_load(metadata_text) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return KnowledgeFile(metadata=metadata, body=body.strip())


@contextlib.contextmanager
def knowledge_repo_lock(root: Path):
    """Exclusive inter-process lock for knowledge repository writes.

    Single-writer discipline (ADR-0030 decision 2) must hold on both Linux and
    Windows. The previous implementation used ``fcntl`` only and silently
    degraded to a no-op wherever ``fcntl`` was unavailable (i.e. Windows),
    which let a second process write concurrently. This uses ``fcntl`` on
    POSIX and ``msvcrt`` on Windows behind one interface so a second process is
    really excluded on both platforms; if neither locking primitive is
    available we raise instead of silently proceeding.
    """
    lock_path = root / ".knowledge-write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Append mode so concurrent openers do not truncate each other's lock file.
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        _acquire_exclusive_lock(lock_file)
        try:
            yield
        finally:
            _release_exclusive_lock(lock_file)


def _acquire_exclusive_lock(lock_file) -> None:
    fcntl = _import_fcntl()
    if fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return
    msvcrt = _import_msvcrt()
    if msvcrt is not None:
        lock_file.seek(0)
        while True:
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.1)
    raise RuntimeError(
        "No cross-platform file lock available (need fcntl on POSIX or msvcrt on Windows)."
    )


def _release_exclusive_lock(lock_file) -> None:
    fcntl = _import_fcntl()
    if fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return
    msvcrt = _import_msvcrt()
    if msvcrt is not None:
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


def _import_fcntl():
    try:
        import fcntl

        return fcntl
    except ImportError:
        return None


def _import_msvcrt():
    try:
        import msvcrt

        return msvcrt
    except ImportError:
        return None


def sha256_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _knowledge_file_metadata(item: MemoryKnowledgeItem, *, body: str | None = None) -> dict[str, Any]:
    now = timezone.now()
    source_refs = list(item.source_refs or _legacy_source_refs(item))
    text_hash = sha256_text(body) if body is not None else item.text_hash
    return {
        "knowledge_id": item.memory_id,
        "legacy_memory_id": item.memory_id,
        "scope": str(item.scope),
        "owner_user_id": item.owner_user_id,
        "kind": str(item.kind),
        "source_code": item.source_code or "chat",
        "source_kind": item.source_kind or "chat",
        "source_refs": source_refs,
        "sensitivity": str(item.sensitivity),
        "scope_tokens": list(item.scope_tokens or []),
        "status": str(item.status),
        "index_status": str(item.index_status),
        "created_at": (item.created_at or now).isoformat(),
        "updated_at": (item.updated_at or now).isoformat(),
        "text_hash": f"sha256:{text_hash}",
        "metadata": _plain_value(dict(item.metadata or {})),
    }


def _plain_value(value):
    if isinstance(value, dict):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value) if type(value).__name__ != type(str(value)).__name__ and isinstance(value, str) else value
    return str(value)


def _legacy_source_refs(item: MemoryKnowledgeItem) -> list[dict[str, str]]:
    refs = []
    if item.source_session_id:
        for message_id in item.source_message_ids or []:
            refs.append(
                {
                    "kind": "chat_message",
                    "value": f"chat_session:{item.source_session_id}/message:{message_id}",
                }
            )
    return refs


def _summary_markdown(*, scope: str, owner_user, items: list[MemoryKnowledgeItem]) -> str:
    title = "Organization knowledge summary" if scope == MemoryKnowledgeItem.Scope.ORGANIZATION else "Personal knowledge summary"
    lines = [f"# {title}", ""]
    if owner_user is not None:
        lines.append(f"Owner user id: {owner_user.id}")
        lines.append("")
    for item in items:
        source_refs = item.source_refs or _legacy_source_refs(item)
        source_text = f" source={source_refs[0]['value']}" if source_refs else ""
        try:
            body = read_knowledge_item_file(item).body
        except ValidationError as exc:
            body = f"[knowledge file error: {exc}]"
        lines.append(f"- `{item.memory_id}` [{item.source_code}] {body}{source_text}")
    return "\n".join(lines).rstrip() + "\n"


def _write_schema_file(root: Path) -> None:
    schema_path = root / "schemas" / "knowledge_file.schema.json"
    if schema_path.exists():
        return
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(
        "{\n"
        '  "$schema": "https://json-schema.org/draft/2020-12/schema",\n'
        '  "type": "object",\n'
        '  "required": ["knowledge_id", "scope", "source_refs", "status", "text_hash"],\n'
        '  "properties": {\n'
        '    "knowledge_id": {"type": "string"},\n'
        '    "scope": {"enum": ["personal", "organization"]},\n'
        '    "source_refs": {"type": "array"},\n'
        '    "status": {"type": "string"},\n'
        '    "text_hash": {"type": "string"}\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )


def _safe_repo_path(root: Path, relative_path: str) -> Path:
    path = (root / relative_path).resolve()
    root_resolved = root.resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError as exc:
        raise ValidationError("Knowledge file path escapes repository root.") from exc
    return path


def _safe_path_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return cleaned.strip("._-") or "unknown"


def _safe_file_stem(value: str) -> str:
    cleaned = _safe_path_part(value)
    if len(cleaned) <= 120:
        return cleaned
    return f"{cleaned[:80]}_{sha256_text(value)[:24]}"


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _ensure_git_identity(root: Path) -> None:
    name = _run_git_optional(root, "config", "user.name").stdout.strip()
    email = _run_git_optional(root, "config", "user.email").stdout.strip()
    if not name:
        _run_git(root, "config", "user.name", "Local Business Memory Writer")
    if not email:
        _run_git(root, "config", "user.email", "memory-writer@local")


def _commit_if_needed(root: Path, message: str) -> None:
    status = _run_git(root, "status", "--porcelain").stdout.strip()
    if not status:
        return
    _run_git(root, "commit", "-m", message)


def _git_head(root: Path) -> str:
    result = _run_git_optional(root, "rev-parse", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else ""


def _run_git_optional(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
