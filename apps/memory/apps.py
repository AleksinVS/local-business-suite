from django.apps import AppConfig


class MemoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.memory"
    verbose_name = "Память ИИ"

    def ready(self):
        # Совместимый pre_delete guard для старых SQLite/multi-db установок.
        from . import signals  # noqa: F401
