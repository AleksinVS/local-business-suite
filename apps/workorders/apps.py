from django.apps import AppConfig


class WorkordersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.workorders'

    def ready(self):
        # Импорт политики и реестра внутри ready(), чтобы не ловить
        # AppRegistryNotReady на импорте моделей во время загрузки приложений.
        from apps.core.media import register_media_policy

        from . import ai_skills, right_panel, source_adapter
        from .media_policies import serve_workorder_media

        ai_skills.register()
        right_panel.register()
        source_adapter.register()
        register_media_policy("workorders", serve_workorder_media)
