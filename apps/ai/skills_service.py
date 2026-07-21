from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.core.ai_skills import (
    AgentSkillDescriptor,
    get_agent_skill,
    normalize_skill_id,
    registered_agent_skills,
)
from .tool_definitions import get_tool_registry


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_LIST_FIELDS = {"object_types", "required_tools", "trigger_examples"}
_CACHE: dict[str, Any] | None = None


def parse_skill_md(file_path: str | Path) -> tuple[dict[str, Any], str]:
    content = Path(file_path).read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    metadata: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip().strip('"')
        if key in _LIST_FIELDS:
            metadata[key] = _parse_list_value(value)
        else:
            metadata[key] = value
    return metadata, match.group(2).strip()


def discover_skills(user: Any | None = None, *, use_cache: bool = True) -> list[dict[str, Any]]:
    global _CACHE
    if use_cache and user is None and _CACHE is not None:
        return [dict(item) for item in _CACHE["catalog"]]

    catalog: dict[str, dict[str, Any]] = {}

    for skill_id, provider in sorted(registered_agent_skills().items()):
        if not _provider_available(provider, user):
            continue
        entry = _normalize_catalog_entry(provider.catalog_entry(), fallback_id=skill_id)
        entry["registration_source"] = "module"
        catalog[entry["id"]] = entry

    for root, source in _contract_skill_roots():
        for entry in _discover_file_skills(root, registration_source=source):
            current = catalog.get(entry["id"])
            if current and current.get("registration_source") == "module":
                continue
            catalog[entry["id"]] = entry

    result = list(catalog.values())
    if user is None:
        _CACHE = {"catalog": [dict(item) for item in result]}
    return result


def load_skill_content(skill_id: str) -> str | None:
    try:
        normalized_id = normalize_skill_id(skill_id)
    except ValidationError:
        return None

    provider = get_agent_skill(normalized_id)
    if provider is not None:
        return provider.load_body()

    for root, _source in reversed(_contract_skill_roots()):
        skill_path = root / normalized_id / "SKILL.md"
        if skill_path.exists() and _is_within_root(skill_path, root):
            try:
                metadata, body = parse_skill_md(skill_path)
                build_file_skill_descriptor(normalized_id, metadata, body)
            except ValidationError:
                return None
            return body
    return None


def clear_skill_catalog_cache() -> None:
    global _CACHE
    _CACHE = None


def build_file_skill_descriptor(skill_id: str, metadata: dict[str, Any], body: str) -> AgentSkillDescriptor:
    normalized_id = normalize_skill_id(skill_id)
    descriptor = AgentSkillDescriptor(
        skill_id=normalized_id,
        name=str(metadata.get("name") or normalized_id).strip(),
        description=str(metadata.get("description") or "").strip(),
        body=body,
        source_code=str(metadata.get("source_code") or "").strip(),
        object_types=tuple(_parse_list_value(metadata.get("object_types"))),
        required_tools=tuple(_parse_list_value(metadata.get("required_tools"))),
        trigger_examples=tuple(_parse_list_value(metadata.get("trigger_examples"))),
    )
    validate_required_tools_exist(descriptor.required_tools)
    return descriptor


def validate_required_tools_exist(required_tools: tuple[str, ...] | list[str]) -> None:
    registry = get_tool_registry()
    missing = [tool_code for tool_code in required_tools if tool_code not in registry]
    if missing:
        raise ValidationError(f"Неизвестные required_tools: {', '.join(sorted(missing))}.")


def _provider_available(provider: Any, user: Any | None) -> bool:
    checker = getattr(provider, "is_available_for_user", None)
    if checker is None:
        return True
    return bool(checker(user))


def _contract_skill_roots() -> tuple[tuple[Path, str], ...]:
    # Defaults first, runtime second: runtime contract skills override default files.
    return (
        (settings.DEFAULT_CONTRACTS_DIR / "ai" / "skills", "contract_default"),
        (settings.RUNTIME_CONTRACTS_DIR / "ai" / "skills", "runtime_contract"),
    )


def _discover_file_skills(root: Path, *, registration_source: str) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    catalog = []
    for item_path in sorted(root.iterdir()):
        if not item_path.is_dir():
            continue
        try:
            skill_id = normalize_skill_id(item_path.name)
        except ValidationError:
            continue
        skill_md = item_path / "SKILL.md"
        if not skill_md.exists() or not _is_within_root(skill_md, root):
            continue
        try:
            metadata, body = parse_skill_md(skill_md)
            descriptor = build_file_skill_descriptor(skill_id, metadata, body)
            entry = descriptor.catalog_entry()
        except ValidationError:
            continue
        entry["registration_source"] = registration_source
        catalog.append(entry)
    return catalog


def _normalize_catalog_entry(entry: dict[str, Any], *, fallback_id: str) -> dict[str, Any]:
    descriptor = AgentSkillDescriptor(
        skill_id=entry.get("id") or fallback_id,
        name=entry.get("name") or fallback_id,
        description=entry.get("description") or "",
        body="catalog entry validation body",
        source_code=entry.get("source_code") or "",
        object_types=tuple(_parse_list_value(entry.get("object_types"))),
        required_tools=tuple(_parse_list_value(entry.get("required_tools"))),
        trigger_examples=tuple(_parse_list_value(entry.get("trigger_examples"))),
    )
    validate_required_tools_exist(descriptor.required_tools)
    return descriptor.catalog_entry()


def _parse_list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [item.strip().strip('"').strip("'") for item in re.split(r"[,;]", text) if item.strip()]


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
