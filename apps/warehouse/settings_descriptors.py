from apps.settings_center.descriptors import SettingDescriptor


def get_settings_descriptors():
    return [
        SettingDescriptor(
            setting_id="warehouse.settings",
            domain="warehouse",
            section="Учёт и сроки годности",
            title="Параметры склада",
            description=(
                "Точность новых единиц измерения и пороги предупреждения "
                "об истечении срока годности."
            ),
            help_topic_id="settings.warehouse.settings",
            storage_kind="runtime_contract",
            value_type="json",
            widget="json_editor",
            write_policy="editable",
            required_permission="manage_settings",
            metadata={
                "settings_path": "LOCAL_BUSINESS_WAREHOUSE_SETTINGS_FILE",
                "validator": "validate_warehouse_settings_payload",
                "document_id": "warehouse.settings",
            },
        )
    ]
