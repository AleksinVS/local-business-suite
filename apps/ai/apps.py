from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    verbose_name = "ИИ"

    def ready(self):
        # Импорт политики и реестра внутри ready(), чтобы не ловить
        # AppRegistryNotReady на импорте моделей во время загрузки приложений.
        from apps.core.media import register_media_policy

        from . import ai_skills
        from .media_policies import serve_chat_attachment_media

        ai_skills.register()
        register_media_policy("chat_attachments", serve_chat_attachment_media)
