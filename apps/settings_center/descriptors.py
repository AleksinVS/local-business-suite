from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .document_security import normalize_sensitive_key


SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "private_key",
    "credential",
)

DOMAIN_LABELS = {
    "core": "Ядро",
    "env": "Окружение",
    "memory": "Память",
    "ai": "ИИ",
    "accounts": "Учетные записи",
    "workorders": "Заявки",
    "waiting_list": "Лист ожидания",
    "settings_center": "Центр настроек",
}

STORAGE_KIND_LABELS = {
    "runtime_contract": "рабочий контракт",
    "env_var": "переменная окружения",
    "django_model": "модель Django",
    "secret_handle": "ссылка на секрет",
}

WRITE_POLICY_LABELS = {
    "editable": "редактируется",
    "read_only": "только чтение",
    "proposal_only": "через заявку",
    "requires_domain_workflow": "через доменный процесс",
    "secret_handle_only": "только ссылка на секрет",
}

SECRET_VALUE_TYPES = frozenset({"secret"})
SECRET_WIDGETS = frozenset({"password", "secret", "secret_handle"})
SECRET_STORAGE_KINDS = frozenset({"secret_handle"})

def runtime_validators() -> dict[str, Any]:
    """Build the single registry of editable runtime-contract validators."""
    from apps.ai import contracts as ai_contracts
    from apps.memory import contracts as memory_contracts
    from apps.waiting_list import contracts as waiting_list_contracts
    from apps.workorders import contracts as workorder_contracts

    def effective_workflow_payload():
        # Lazy import avoids a cycle: contract_store imports domain validators,
        # while the settings registry resolves these validator names.
        from apps.core.contract_store import get_contract

        return get_contract("workflow_rules")

    def validate_memory_sources_with_effective_snapshot(payload):
        # Source validation is cross-document validation.  Obtain the related
        # profiles/routing/ingestion documents through one repository snapshot
        # so this compatibility validator cannot silently read legacy files.
        from apps.settings_center.document_repository import ConfigDocumentRepository

        snapshots = ConfigDocumentRepository().get_snapshot(
            (
                "memory.contract.sources",
                "memory.contract.profiles",
                "memory.contract.routing",
                "memory.contract.ingestion_profiles",
            )
        )
        memory_contracts.validate_memory_sources_payload(
            payload,
            profiles_payload=snapshots["memory.contract.profiles"].payload,
            routing_payload=snapshots["memory.contract.routing"].payload,
            ingestion_profiles_payload=snapshots["memory.contract.ingestion_profiles"].payload,
        )

    return {
        "validate_role_rules_payload": lambda payload: workorder_contracts.validate_role_rules_payload(
            payload,
            workflow_payload=effective_workflow_payload(),
        ),
        "validate_workorder_status_colors_payload": lambda payload: workorder_contracts.validate_workorder_status_colors_payload(
            payload,
            workflow_payload=effective_workflow_payload(),
        ),
        "validate_waiting_list_status_colors_payload": waiting_list_contracts.validate_waiting_list_status_colors_payload,
        "validate_workflow_rules_payload": workorder_contracts.validate_workflow_rules_payload,
        "validate_ai_registry_payload": ai_contracts.validate_ai_registry_payload,
        "validate_ai_tools_payload": ai_contracts.validate_ai_tools_payload,
        "validate_ai_task_types_payload": ai_contracts.validate_ai_task_types_payload,
        "validate_ai_chat_settings_payload": ai_contracts.validate_ai_chat_settings_payload,
        "validate_memory_profiles_payload": memory_contracts.validate_memory_profiles_payload,
        "validate_memory_routing_payload": memory_contracts.validate_memory_routing_payload,
        "validate_memory_ingestion_profiles_payload": memory_contracts.validate_memory_ingestion_profiles_payload,
        "validate_memory_file_organization_profiles_payload": memory_contracts.validate_memory_file_organization_profiles_payload,
        "validate_memory_graph_schema_payload": memory_contracts.validate_memory_graph_schema_payload,
        "validate_memory_sources_payload": validate_memory_sources_with_effective_snapshot,
        "validate_memory_trust_policy_payload": memory_contracts.validate_memory_trust_policy_payload,
        "validate_memory_claims_policy_payload": memory_contracts.validate_memory_claims_policy_payload,
        "validate_memory_retrieval_budget_payload": memory_contracts.validate_memory_retrieval_budget_payload,
    }


def runtime_validator_names() -> frozenset[str]:
    return frozenset(runtime_validators())


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
    # Product settings use the role capability. Django ``is_staff`` remains
    # exclusively the gate for Django Admin.
    required_permission: str = "manage_settings"
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

    @property
    def is_secret(self) -> bool:
        """Whether this descriptor may carry a secret or secret handle."""
        return bool(
            self.sensitivity == "secret"
            or self.value_type in SECRET_VALUE_TYPES
            or self.widget in SECRET_WIDGETS
            or self.storage_kind in SECRET_STORAGE_KINDS
        )

    @property
    def domain_label(self) -> str:
        return DOMAIN_LABELS.get(self.domain, self.domain)

    @property
    def storage_kind_label(self) -> str:
        return STORAGE_KIND_LABELS.get(self.storage_kind, self.storage_kind)

    @property
    def write_policy_label(self) -> str:
        return WRITE_POLICY_LABELS.get(self.write_policy, self.write_policy)

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
            key_text = normalize_sensitive_key(key)
            if any(part in key_text for part in SENSITIVE_KEY_PARTS):
                masked[key] = "***"
            else:
                masked[key] = mask_sensitive(item)
        return masked
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value
