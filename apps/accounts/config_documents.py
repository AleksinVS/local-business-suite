from apps.settings_center.document_specs import ConfigDocumentSpec
from apps.workorders.contracts import validate_role_rules_payload


def validate_role_rules_document(candidate):
    validate_role_rules_payload(candidate)


def cross_validate_role_rules_document(candidate, related_payloads):
    validate_role_rules_payload(
        candidate,
        workflow_payload=related_payloads["core.contract.workflow_rules"],
    )


def get_document_specs():
    return [
        ConfigDocumentSpec(
            document_id="core.contract.role_rules",
            domain="accounts",
            storage_policy="database_override",
            default_path="contracts/role_rules.json",
            schema_version=1,
            validator=validate_role_rules_document,
            failure_policy="fail_closed",
            write_policy="requires_domain_workflow",
            required_permission="manage_settings",
            owner="accounts",
            legacy_settings_path="LOCAL_BUSINESS_ROLE_RULES_FILE",
            cross_document_ids=("core.contract.workflow_rules",),
            cross_validator=cross_validate_role_rules_document,
            consumer_classes=("accounts", "workorders", "ai", "memory"),
            sensitivity="restricted",
        )
    ]
