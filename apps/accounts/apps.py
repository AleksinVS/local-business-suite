from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self):
        """Регистрация сигналов при загрузке приложения"""
        import apps.accounts.signals
