from django.apps import AppConfig


class SettingsCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.settings_center"
    verbose_name = "Центр настроек"

    def ready(self):
        from . import checks  # noqa: F401
        from . import right_panel

        right_panel.register()
