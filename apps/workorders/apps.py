from django.apps import AppConfig


class WorkordersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.workorders'

    def ready(self):
        from . import source_adapter

        source_adapter.register()
