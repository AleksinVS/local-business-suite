from apps.settings_center.document_specs import ConfigDocumentSpec
from apps.waiting_list.contracts import validate_waiting_list_status_colors_payload


def get_document_specs():
    return [
        ConfigDocumentSpec(
            document_id="waiting_list.contract.status_colors",
            domain="waiting_list",
            storage_policy="database_override",
            default_path="contracts/waiting_list_status_colors.json",
            schema_version=1,
            validator=validate_waiting_list_status_colors_payload,
            failure_policy="visible_default_fallback",
            write_policy="editable",
            required_permission="manage_settings",
            owner="waiting_list",
            legacy_settings_path="LOCAL_BUSINESS_WAITING_LIST_STATUS_COLORS_FILE",
            consumer_classes=("waiting_list",),
        )
    ]
