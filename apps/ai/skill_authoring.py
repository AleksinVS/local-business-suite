from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.ai_skills import normalize_skill_id
from apps.core.file_locks import access_control_write_lock_path, exclusive_file_lock

from .skills_service import (
    build_file_skill_descriptor,
    clear_skill_catalog_cache,
    validate_required_tools_exist,
)


def can_manage_ai_skills(user: Any) -> bool:
    if not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return False
    from django.contrib.auth import get_user_model

    current = get_user_model().objects.filter(pk=user.pk, is_active=True).first()
    if not current:
        return False
    if getattr(current, "is_superuser", False):
        return True
    from apps.core.contract_store import get_contract

    role_rules = get_contract("role_rules")
    role_names = set(current.groups.values_list("name", flat=True))
    return any(bool(role_rules.get(role, {}).get("manage_ai_skills")) for role in role_names)


def create_or_update_runtime_skill_for_actor(*, actor: Any, payload: dict[str, Any]) -> dict[str, Any]:
    # Use the same cross-process lock as access-control contract writes.  The
    # capability is checked again after taking the lock so a role revocation
    # racing this request cannot be bypassed by a stale actor object.
    with exclusive_file_lock(access_control_write_lock_path(), timeout=10.0):
        if not can_manage_ai_skills(actor):
            raise PermissionDenied("Пользователю недоступно управление навыками ИИ.")
        document = build_runtime_skill_document(payload)
        skill_id = document["skill_id"]
        target_dir = _runtime_skill_dir(skill_id)
        _reject_symlink_path(target_dir, label="Директория рабочего навыка")
        _ensure_instruction_only_dir(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "SKILL.md"
        _reject_symlink_path(target_path, label="Файл рабочего навыка")
        fd, tmp_name = tempfile.mkstemp(prefix=".SKILL.md.", suffix=".tmp", dir=target_dir)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(document["content"])
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, target_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
    clear_skill_catalog_cache()
    return {
        "status": "ok",
        "skill_id": skill_id,
        "path": str(target_path.relative_to(settings.RUNTIME_CONTRACTS_DIR)),
        "required_tools": document["required_tools"],
        "message": "Рабочий навык сохранен.",
    }


def build_runtime_skill_document(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload or {})
    frontmatter = dict(payload.get("frontmatter") or {})
    skill_id = normalize_skill_id(payload.get("skill_id") or frontmatter.get("id") or frontmatter.get("skill_id"))
    name = str(payload.get("name") or frontmatter.get("name") or "").strip()
    description = str(payload.get("description") or frontmatter.get("description") or "").strip()
    source_code = str(payload.get("source_code") or frontmatter.get("source_code") or "").strip()
    object_types = _normalize_list(payload.get("object_types", frontmatter.get("object_types")))
    required_tools = _normalize_list(payload.get("required_tools", frontmatter.get("required_tools")))
    trigger_examples = _normalize_list(payload.get("trigger_examples", frontmatter.get("trigger_examples")))
    body = str(payload.get("body") or payload.get("instructions") or "").strip()

    if not name:
        raise ValidationError("Нужно указать название навыка.")
    if not description:
        raise ValidationError("Нужно указать описание навыка.")
    if not body:
        raise ValidationError("Нужно указать инструкции навыка.")
    if payload.get("scripts") or payload.get("assets") or payload.get("files"):
        raise ValidationError("В MVP рабочие навыки могут содержать только инструкции.")

    descriptor = build_file_skill_descriptor(
        skill_id,
        {
            "name": name,
            "description": description,
            "source_code": source_code,
            "object_types": object_types,
            "required_tools": required_tools,
            "trigger_examples": trigger_examples,
        },
        body,
    )
    validate_required_tools_exist(descriptor.required_tools)
    content = _render_skill_md(
        name=descriptor.name,
        description=descriptor.description,
        source_code=descriptor.source_code,
        object_types=descriptor.object_types,
        required_tools=descriptor.required_tools,
        trigger_examples=descriptor.trigger_examples,
        body=descriptor.body,
    )
    return {
        "skill_id": descriptor.skill_id,
        "required_tools": list(descriptor.required_tools),
        "content": content,
    }


def validate_runtime_skill_file(path: Path) -> dict[str, Any]:
    from .skills_service import parse_skill_md

    path = Path(path)
    skill_id = normalize_skill_id(path.parent.name)
    if path.name != "SKILL.md":
        raise ValidationError("Файл рабочего навыка должен называться SKILL.md.")
    if not _is_within_root(path, _runtime_skills_root()):
        raise ValidationError("Файл рабочего навыка находится вне директории навыков.")
    metadata, body = parse_skill_md(path)
    descriptor = build_file_skill_descriptor(skill_id, metadata, body)
    return descriptor.catalog_entry()


def list_runtime_skill_files() -> list[Path]:
    root = _runtime_skills_root()
    if not root.exists():
        return []
    return sorted(
        path / "SKILL.md"
        for path in root.iterdir()
        if path.is_dir()
        and not path.is_symlink()
        and (path / "SKILL.md").is_file()
        and not (path / "SKILL.md").is_symlink()
    )


def _runtime_skill_dir(skill_id: str) -> Path:
    root = _runtime_skills_root()
    return root / normalize_skill_id(skill_id)


def _runtime_skills_root() -> Path:
    runtime_root = Path(settings.RUNTIME_CONTRACTS_DIR).resolve(strict=False)
    configured = Path(settings.RUNTIME_CONTRACTS_DIR) / "ai" / "skills"
    if configured.is_symlink():
        raise ValidationError("Корень рабочих навыков не может быть символической ссылкой.")
    resolved = configured.resolve(strict=False)
    try:
        resolved.relative_to(runtime_root)
    except ValueError as exc:
        raise ValidationError(
            "Корень рабочих навыков находится вне директории рабочих контрактов."
        ) from exc
    return resolved


def _reject_symlink_path(path: Path, *, label: str) -> None:
    """Reject existing symlink components before any write or replacement."""
    path = Path(path)
    root = _runtime_skills_root()
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError as exc:
        raise ValidationError(f"{label} находится вне корня рабочих навыков.") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValidationError(f"{label} не может быть символической ссылкой.")


def _ensure_instruction_only_dir(path: Path) -> None:
    if not path.exists():
        return
    extra = [
        child.name
        for child in path.iterdir()
        if child.name != "SKILL.md"
        and not (child.name.startswith(".SKILL.md.") and child.name.endswith(".tmp"))
    ]
    if extra:
        raise ValidationError("Директория рабочего навыка содержит неподдерживаемые файлы.")


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]


def _render_skill_md(
    *,
    name: str,
    description: str,
    source_code: str,
    object_types: tuple[str, ...],
    required_tools: tuple[str, ...],
    trigger_examples: tuple[str, ...],
    body: str,
) -> str:
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if source_code:
        lines.append(f"source_code: {source_code}")
    if object_types:
        lines.append(f"object_types: {', '.join(object_types)}")
    if required_tools:
        lines.append(f"required_tools: {', '.join(required_tools)}")
    if trigger_examples:
        lines.append(f"trigger_examples: {'; '.join(trigger_examples)}")
    lines.extend(["---", "", body.strip(), ""])
    return "\n".join(lines)


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
