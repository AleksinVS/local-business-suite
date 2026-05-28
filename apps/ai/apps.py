from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    verbose_name = "AI"

    def ready(self):
        from . import ai_skills

        ai_skills.register()
