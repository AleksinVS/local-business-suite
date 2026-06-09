from django.apps import AppConfig


class MemoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.memory"
    verbose_name = "Память ИИ"

    def ready(self):
        # Регистрация pre_delete обработчика, который поддерживает
        # SET_NULL-семантику для MemoryWriteRequest.session при удалении
        # ChatSession. Подробности в apps/memory/signals.py.
        from . import signals  # noqa: F401
