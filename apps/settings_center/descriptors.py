from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "private_key",
    "credential",
)


@dataclass(frozen=True)
class SettingDescriptor:
    setting_id: str
    domain: str
    section: str
    title: str
    description: str
    help_topic_id: str
    storage_kind: str
    value_type: str = "string"
    widget: str = "text"
    write_policy: str = "read_only"
    required_permission: str = "settings_center.manage"
    sensitivity: str = "internal"
    masking_policy: str = "default"
    requires_restart: bool = False
    requires_reindex: bool = False
    audit_category: str = "settings"
    choices: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_editable(self) -> bool:
        return self.write_policy == "editable"

    @property
    def is_proposal_only(self) -> bool:
        return self.write_policy == "proposal_only"

    def safe_context(self, current_value: Any = None) -> dict[str, Any]:
        context = {
            "setting_id": self.setting_id,
            "domain": self.domain,
            "section": self.section,
            "title": self.title,
            "description": self.description,
            "help_topic_id": self.help_topic_id,
            "storage_kind": self.storage_kind,
            "value_type": self.value_type,
            "widget": self.widget,
            "write_policy": self.write_policy,
            "required_permission": self.required_permission,
            "sensitivity": self.sensitivity,
            "requires_restart": self.requires_restart,
            "requires_reindex": self.requires_reindex,
            "choices": list(self.choices),
            "metadata": mask_sensitive(self.metadata),
        }
        if current_value is not None:
            context["current_value_summary"] = summarize_value(current_value)
        return mask_sensitive(context)


def summarize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: summarize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) > 10:
            return {"items": len(value), "sample": [summarize_value(item) for item in value[:3]]}
        return [summarize_value(item) for item in value]
    if isinstance(value, str) and len(value) > 180:
        return value[:177] + "..."
    return value


def mask_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SENSITIVE_KEY_PARTS):
                masked[key] = "***"
            else:
                masked[key] = mask_sensitive(item)
        return masked
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value
