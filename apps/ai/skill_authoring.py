from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core.ai_skills import normalize_skill_id

from .skills_service import (
    build_file_skill_descriptor,
    clear_skill_catalog_cache,
    validate_required_tools_exist,
)


AI_MANAGE_SKILLS_PERMISSION = "ai.manage_skills"


def can_manage_ai_skills(user: Any) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    has_perm = getattr(user, "has_perm", None)
    if callable(has_perm) and has_perm(AI_MANAGE_SKILLS_PERMISSION):
        return True
    role_rules = getattr(settings, "LOCAL_BUSINESS_ROLE_RULES", {}) or {}
    role_names = set(user.groups.values_list("name", flat=True))
    return any(bool(role_rules.get(role, {}).get("manage_ai_skills")) for role in role_names)


def create_or_update_runtime_skill_for_actor(*, actor: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if not can_manage_ai_skills(actor):
        raise PermissionDenied("AI skill management is not allowed for this user.")
    document = build_runtime_skill_document(payload)
    skill_id = document["skill_id"]
    target_dir = _runtime_skill_dir(skill_id)
    _ensure_instruction_only_dir(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "SKILL.md"
    tmp_path = target_dir / ".SKILL.md.tmp"
    tmp_path.write_text(document["content"], encoding="utf-8")
    os.replace(tmp_path, target_path)
    clear_skill_catalog_cache()
    return {
        "status": "ok",
        "skill_id": skill_id,
        "path": str(target_path.relative_to(settings.RUNTIME_CONTRACTS_DIR)),
        "required_tools": document["required_tools"],
        "message": "Runtime skill saved.",
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
        raise ValidationError("Skill name is required.")
    if not description:
        raise ValidationError("Skill description is required.")
    if not body:
        raise ValidationError("Skill body is required.")
    if payload.get("scripts") or payload.get("assets") or payload.get("files"):
        raise ValidationError("Runtime skills are instruction-only in this MVP.")

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
        raise ValidationError("Runtime skill file must be named SKILL.md.")
    if not _is_within_root(path, settings.RUNTIME_CONTRACTS_DIR / "ai" / "skills"):
        raise ValidationError("Runtime skill file is outside the skills directory.")
    metadata, body = parse_skill_md(path)
    descriptor = build_file_skill_descriptor(skill_id, metadata, body)
    return descriptor.catalog_entry()


def list_runtime_skill_files() -> list[Path]:
    root = settings.RUNTIME_CONTRACTS_DIR / "ai" / "skills"
    if not root.exists():
        return []
    return sorted(path / "SKILL.md" for path in root.iterdir() if path.is_dir() and (path / "SKILL.md").exists())


def _runtime_skill_dir(skill_id: str) -> Path:
    root = settings.RUNTIME_CONTRACTS_DIR / "ai" / "skills"
    return root / normalize_skill_id(skill_id)


def _ensure_instruction_only_dir(path: Path) -> None:
    if not path.exists():
        return
    extra = [child.name for child in path.iterdir() if child.name not in {"SKILL.md", ".SKILL.md.tmp"}]
    if extra:
        raise ValidationError("Runtime skill directory contains unsupported files.")


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
