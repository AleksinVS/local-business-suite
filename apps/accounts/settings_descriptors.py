from apps.settings_center.descriptors import SettingDescriptor


def get_settings_descriptors():
    return [
        SettingDescriptor(
            setting_id="accounts.users.local_management",
            domain="accounts",
            section="Users",
            title="Local portal users",
            description="Create, disable and update local portal users, departments and local groups.",
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
            section="Directory",
            title="Active Directory identity link",
            description="Explicitly links a local portal user to AD SID, sAMAccountName, UPN and DN metadata.",
            help_topic_id="settings.accounts.user.ad_identity_link",
            storage_kind="django_model",
            value_type="object",
            widget="ad_identity_link",
            write_policy="requires_domain_workflow",
            required_permission="settings_center.manage_users",
        ),
    ]
