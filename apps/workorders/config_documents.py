from apps.settings_center.document_specs import ConfigDocumentSpec
from apps.workorders.contracts import (
    validate_workflow_rules_payload,
    validate_workorder_status_colors_payload,
)


def cross_validate_workorder_status_colors(candidate, related_payloads):
    validate_workorder_status_colors_payload(
        candidate,
        workflow_payload=related_payloads["core.contract.workflow_rules"],
    )


def get_document_specs():
    return [
        ConfigDocumentSpec(
            document_id="core.contract.workflow_rules",
            domain="workorders",
            storage_policy="database_override",
            default_path="contracts/workflow_rules.json",
            schema_version=1,
            validator=validate_workflow_rules_payload,
            failure_policy="fail_closed",
            write_policy="editable",
            required_permission="manage_settings",
            owner="workorders",
            legacy_settings_path="LOCAL_BUSINESS_WORKFLOW_RULES_FILE",
            consumer_classes=("workorders", "accounts"),
            sensitivity="restricted",
        ),
        ConfigDocumentSpec(
            document_id="workorders.contract.status_colors",
            domain="workorders",
            storage_policy="database_override",
            default_path="contracts/workorder_status_colors.json",
            schema_version=1,
            validator=validate_workorder_status_colors_payload,
            failure_policy="visible_default_fallback",
            write_policy="editable",
            required_permission="manage_settings",
            owner="workorders",
            legacy_settings_path="LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE",
            cross_document_ids=("core.contract.workflow_rules",),
            cross_validator=cross_validate_workorder_status_colors,
            consumer_classes=("workorders",),
        ),
    ]
