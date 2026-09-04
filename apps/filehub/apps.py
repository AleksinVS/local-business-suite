from django.apps import AppConfig


class FilehubConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.filehub"
    verbose_name = "Автоупорядочивание файлов (заморожено)"

    def ready(self):
        from . import autocomplete

        autocomplete.register()
