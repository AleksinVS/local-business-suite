from __future__ import annotations

import importlib
from dataclasses import replace
from functools import lru_cache

from .descriptors import (
    runtime_validator_names,
    SECRET_STORAGE_KINDS,
    SECRET_VALUE_TYPES,
    SECRET_WIDGETS,
    SettingDescriptor,
)


KNOWN_REQUIRED_PERMISSIONS = frozenset({"manage_settings", "manage_users"})
EXPECTED_RUNTIME_DOCUMENT_IDS = frozenset(
    {
        "core.contract.role_rules",
        "core.contract.workflow_rules",
        "workorders.contract.status_colors",
        "waiting_list.contract.status_colors",
        "ai.contract.registry",
        "ai.contract.tools",
        "ai.contract.task_types",
        "ai.contract.models",
        "ai.contract.chat_settings",
        "memory.contract.sources",
        "memory.contract.profiles",
        "memory.contract.routing",
        "memory.contract.trust_policy",
        "memory.contract.claims_policy",
        "memory.contract.retrieval_budget",
        "memory.contract.ingestion_profiles",
        "memory.contract.file_organization_profiles",
        "memory.contract.graph_schema",
    }
)


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
    # Compatibility projection: document specs are authoritative for runtime
    # contract path/validator and static/domain-workflow editability.
    from .document_registry import get_document_registry

    document_specs = {spec.document_id: spec for spec in get_document_registry().all()}
    projected = []
    for descriptor in descriptors:
        spec = document_specs.get(descriptor.setting_id)
        if not spec or descriptor.storage_kind != "runtime_contract":
            projected.append(descriptor)
            continue
        metadata = dict(descriptor.metadata)
        if spec.legacy_settings_path:
            metadata["settings_path"] = spec.legacy_settings_path
        if spec.validator is not None:
            metadata["validator_callable"] = spec.validator
        metadata.update(
            {
                "storage_policy": spec.storage_policy,
                "active_backend": spec.active_backend,
                "failure_policy": spec.failure_policy,
                "delivery_scope": spec.delivery_scope,
                "cross_document_ids": spec.cross_document_ids,
            }
        )
        projected.append(
            replace(
                descriptor,
                metadata=metadata,
                write_policy=spec.write_policy,
                required_permission=spec.required_permission,
                sensitivity=spec.sensitivity,
                requires_restart=spec.requires_restart,
                requires_reindex=spec.requires_reindex,
            )
        )
    runtime_ids = {
        descriptor.setting_id
        for descriptor in projected
        if descriptor.storage_kind == "runtime_contract"
    }
    if runtime_ids != EXPECTED_RUNTIME_DOCUMENT_IDS:
        raise ValueError("Runtime descriptor/document spec parity mismatch")
    return SettingsRegistry(projected)


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
        validator_callable = descriptor.metadata.get("validator_callable")
        legacy_validator = descriptor.metadata.get("validator")
        if validator_callable is not None and not callable(validator_callable):
            raise ValueError(
                f"Editable runtime descriptor '{descriptor.setting_id}' has a non-callable validator."
            )
        if validator_callable is None and legacy_validator not in runtime_validator_names():
            raise ValueError(
                f"Editable runtime descriptor '{descriptor.setting_id}' has no resolvable validator."
            )
