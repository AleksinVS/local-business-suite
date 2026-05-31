from apps.settings_center.descriptors import SettingDescriptor


def get_settings_descriptors():
    return [
        SettingDescriptor(
            setting_id="workorders.contract.status_colors",
            domain="workorders",
            section="Внешний вид",
            title="Цвета статусов заявок",
            description="Палитра статусов для строк дерева заявок и статусных меток.",
            help_topic_id="settings.workorders.contract.status_colors",
            storage_kind="runtime_contract",
            value_type="json",
            widget="status_color_palette",
            write_policy="editable",
            required_permission="settings_center.manage",
            metadata={
                "settings_path": "LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE",
                "settings_payload_attr": "LOCAL_BUSINESS_WORKORDER_STATUS_COLORS",
                "validator": "validate_workorder_status_colors_payload",
            },
        ),
    ]
