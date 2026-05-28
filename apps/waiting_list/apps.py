from django.apps import AppConfig


class WaitingListConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.waiting_list"
    verbose_name = "Лист ожидания"

    def ready(self):
        from . import source_adapter

        source_adapter.register()
