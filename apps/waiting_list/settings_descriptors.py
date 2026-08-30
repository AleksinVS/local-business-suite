from apps.settings_center.descriptors import SettingDescriptor


def get_settings_descriptors():
    return [
        SettingDescriptor(
            setting_id="waiting_list.contract.status_colors",
            domain="waiting_list",
            section="Внешний вид",
            title="Цвета статусов листа ожидания",
            description="Палитра статусных меток и переключателя состояния записи.",
            help_topic_id="settings.waiting_list.contract.status_colors",
            storage_kind="runtime_contract",
            value_type="json",
            widget="status_color_palette",
            write_policy="editable",
            required_permission="manage_settings",
            metadata={
                "settings_path": "LOCAL_BUSINESS_WAITING_LIST_STATUS_COLORS_FILE",
                "settings_payload_attr": "LOCAL_BUSINESS_WAITING_LIST_STATUS_COLORS",
                "validator": "validate_waiting_list_status_colors_payload",
                "palette_route_name": "settings_center:waiting_list_status_colors",
            },
        ),
    ]
