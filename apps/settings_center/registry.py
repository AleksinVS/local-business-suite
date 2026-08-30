from __future__ import annotations

import importlib
from functools import lru_cache

from .descriptors import (
    runtime_validator_names,
    SECRET_STORAGE_KINDS,
    SECRET_VALUE_TYPES,
    SECRET_WIDGETS,
    SettingDescriptor,
)


KNOWN_REQUIRED_PERMISSIONS = frozenset({"manage_settings", "manage_users"})


DESCRIPTOR_MODULES = (
    "apps.core.settings_descriptors",
    "apps.accounts.settings_descriptors",
    "apps.workorders.settings_descriptors",
    "apps.waiting_list.settings_descriptors",
    "apps.ai.settings_descriptors",
    "apps.memory.settings_descriptors",
)


class SettingsRegistry:
    def __init__(self, descriptors):
        for descriptor in descriptors:
            _validate_descriptor_security(descriptor)
        self._descriptors = {descriptor.setting_id: descriptor for descriptor in descriptors}

    def all(self):
        return list(self._descriptors.values())

    def get(self, setting_id: str) -> SettingDescriptor:
        try:
            return self._descriptors[setting_id]
        except KeyError as exc:
            raise LookupError(f"Unknown setting_id '{setting_id}'.") from exc

    def by_domain(self):
        domains = {}
        for descriptor in self.all():
            domain = domains.setdefault(
                descriptor.domain,
                {"domain": descriptor.domain, "sections": {}, "descriptors": []},
            )
            domain["descriptors"].append(descriptor)
            domain["sections"].setdefault(descriptor.section, []).append(descriptor)
        return domains


@lru_cache(maxsize=1)
def get_registry() -> SettingsRegistry:
    descriptors = []
    seen = set()
    for module_path in DESCRIPTOR_MODULES:
        module = importlib.import_module(module_path)
        for descriptor in module.get_settings_descriptors():
            if not isinstance(descriptor, SettingDescriptor):
                raise TypeError(f"{module_path} returned non-SettingDescriptor value.")
            if descriptor.setting_id in seen:
                raise ValueError(f"Duplicate setting_id '{descriptor.setting_id}'.")
            seen.add(descriptor.setting_id)
            descriptors.append(descriptor)
    return SettingsRegistry(descriptors)


def _validate_descriptor_security(descriptor: SettingDescriptor) -> None:
    """Fail closed when descriptor metadata disagrees about secret handling."""
    secret_signal = bool(
        descriptor.sensitivity == "secret"
        or descriptor.value_type in SECRET_VALUE_TYPES
        or descriptor.widget in SECRET_WIDGETS
        or descriptor.storage_kind in SECRET_STORAGE_KINDS
    )
    if secret_signal and descriptor.sensitivity != "secret":
        raise ValueError(
            f"Descriptor '{descriptor.setting_id}' has secret metadata without sensitivity='secret'."
        )
    if descriptor.sensitivity == "secret" and not (
        descriptor.value_type in SECRET_VALUE_TYPES
        or descriptor.widget in SECRET_WIDGETS
        or descriptor.storage_kind in SECRET_STORAGE_KINDS
    ):
        raise ValueError(
            f"Descriptor '{descriptor.setting_id}' is marked secret without a secret value type, widget, or storage kind."
        )
    if descriptor.required_permission not in KNOWN_REQUIRED_PERMISSIONS:
        raise ValueError(
            f"Descriptor '{descriptor.setting_id}' has an unknown required_permission."
        )
    if descriptor.storage_kind == "runtime_contract" and descriptor.is_editable:
        if not descriptor.metadata.get("settings_path"):
            raise ValueError(
                f"Editable runtime descriptor '{descriptor.setting_id}' must define settings_path."
            )
        if not descriptor.metadata.get("validator"):
            raise ValueError(
                f"Editable runtime descriptor '{descriptor.setting_id}' must define validator."
            )
        if descriptor.metadata["validator"] not in runtime_validator_names():
            raise ValueError(
                f"Editable runtime descriptor '{descriptor.setting_id}' has an unknown validator."
            )
