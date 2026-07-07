from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'

    def ready(self):
        # Регистрирует system checks приложения (в т.ч. валидацию бизнес-контрактов
        # с тегом ``contracts``), которая раньше выполнялась на импорте settings.
        from . import checks  # noqa: F401
