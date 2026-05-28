from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from django.core.exceptions import ValidationError


_SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,78}[a-z0-9]$")
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_.:-]+$")


@runtime_checkable
class AgentSkillProvider(Protocol):
    skill_id: str
    name: str
    description: str
    source_code: str
    object_types: tuple[str, ...]
    required_tools: tuple[str, ...]
    trigger_examples: tuple[str, ...]

    def is_available_for_user(self, user: Any | None) -> bool:
        """Return False when the skill must be hidden from the user."""

    def catalog_entry(self) -> dict[str, Any]:
        """Return safe catalog metadata without the full skill body."""

    def load_body(self) -> str:
        """Return the full privileged workflow instructions."""


@dataclass(frozen=True)
class AgentSkillDescriptor:
    skill_id: str
    name: str
    description: str
    body: str
    source_code: str = ""
    object_types: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    trigger_examples: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_id = normalize_skill_id(self.skill_id)
        normalized_name = str(self.name or "").strip()
        normalized_description = str(self.description or "").strip()
        normalized_body = str(self.body or "").strip()
        if not normalized_name:
            raise ValidationError("Agent skill name must not be empty.")
        if not normalized_description:
            raise ValidationError("Agent skill description must not be empty.")
        if not normalized_body:
            raise ValidationError("Agent skill body must not be empty.")
        object.__setattr__(self, "skill_id", normalized_id)
        object.__setattr__(self, "name", normalized_name[:120])
        object.__setattr__(self, "description", normalized_description[:1000])
        object.__setattr__(self, "body", normalized_body)
        object.__setattr__(self, "source_code", normalize_optional_identifier(self.source_code, "source_code"))
        object.__setattr__(
            self,
            "object_types",
            tuple(normalize_optional_identifier(item, "object_type") for item in self.object_types if str(item or "").strip()),
        )
        object.__setattr__(
            self,
            "required_tools",
            tuple(normalize_tool_code(item) for item in self.required_tools if str(item or "").strip()),
        )
        object.__setattr__(
            self,
            "trigger_examples",
            tuple(str(item or "").strip()[:240] for item in self.trigger_examples if str(item or "").strip()),
        )

    def is_available_for_user(self, user: Any | None) -> bool:
        return True

    def catalog_entry(self) -> dict[str, Any]:
        return {
            "id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "source_code": self.source_code,
            "object_types": list(self.object_types),
            "required_tools": list(self.required_tools),
            "trigger_examples": list(self.trigger_examples),
        }

    def load_body(self) -> str:
        return self.body


_SKILLS: dict[str, AgentSkillProvider] = {}


def register_agent_skill(provider: AgentSkillProvider, *, replace: bool = False) -> AgentSkillProvider:
    skill_id = normalize_skill_id(getattr(provider, "skill_id", ""))
    if skill_id in _SKILLS and not replace:
        raise ValidationError(f"Agent skill '{skill_id}' is already registered.")
    _validate_provider(provider)
    _SKILLS[skill_id] = provider
    return provider


def unregister_agent_skill(skill_id: str) -> None:
    _SKILLS.pop(normalize_skill_id(skill_id), None)


def get_agent_skill(skill_id: str) -> AgentSkillProvider | None:
    return _SKILLS.get(normalize_skill_id(skill_id))


def registered_agent_skills() -> dict[str, AgentSkillProvider]:
    return dict(_SKILLS)


def clear_agent_skills() -> None:
    _SKILLS.clear()


def normalize_skill_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized or not _SKILL_ID_RE.match(normalized):
        raise ValidationError("Agent skill id is invalid.")
    if ".." in normalized or "/" in normalized or "\\" in normalized:
        raise ValidationError("Agent skill id is invalid.")
    return normalized


def normalize_tool_code(value: Any) -> str:
    normalized = normalize_optional_identifier(value, "tool_code")
    if not normalized:
        raise ValidationError("Agent skill tool_code must not be empty.")
    return normalized


def normalize_optional_identifier(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if len(normalized) > 120 or not _IDENTIFIER_RE.match(normalized):
        raise ValidationError(f"Agent skill {field_name} is invalid.")
    return normalized


def _validate_provider(provider: AgentSkillProvider) -> None:
    entry = provider.catalog_entry()
    if normalize_skill_id(entry.get("id")) != normalize_skill_id(getattr(provider, "skill_id", "")):
        raise ValidationError("Agent skill provider returned mismatched id.")
    if not str(provider.load_body() or "").strip():
        raise ValidationError("Agent skill provider returned empty body.")
