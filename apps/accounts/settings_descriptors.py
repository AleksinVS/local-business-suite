from apps.settings_center.descriptors import SettingDescriptor


def get_settings_descriptors():
    return [
        SettingDescriptor(
            setting_id="accounts.users.local_management",
            domain="accounts",
            section="Пользователи",
            title="Локальные пользователи портала",
            description="Создание, отключение и обновление локальных пользователей, подразделений и локальных групп.",
            help_topic_id="settings.accounts.users.local_management",
            storage_kind="django_model",
            value_type="object",
            widget="user_management",
            write_policy="requires_domain_workflow",
            required_permission="settings_center.manage_users",
        ),
        SettingDescriptor(
            setting_id="accounts.user.ad_identity_link",
            domain="accounts",
            section="Каталог",
            title="Связь с учетной записью Active Directory",
            description="Явно связывает локального пользователя портала с AD SID, sAMAccountName, UPN и DN.",
            help_topic_id="settings.accounts.user.ad_identity_link",
            storage_kind="django_model",
            value_type="object",
            widget="ad_identity_link",
            write_policy="requires_domain_workflow",
            required_permission="settings_center.manage_users",
        ),
    ]
