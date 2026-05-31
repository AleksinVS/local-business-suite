from __future__ import annotations

import importlib
from functools import lru_cache

from .descriptors import SettingDescriptor


DESCRIPTOR_MODULES = (
    "apps.core.settings_descriptors",
    "apps.accounts.settings_descriptors",
    "apps.workorders.settings_descriptors",
    "apps.ai.settings_descriptors",
    "apps.memory.settings_descriptors",
)


class SettingsRegistry:
    def __init__(self, descriptors):
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
