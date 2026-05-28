from django.apps import AppConfig


class WorkordersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.workorders'

    def ready(self):
        from . import ai_skills, right_panel, source_adapter

        ai_skills.register()
        right_panel.register()
        source_adapter.register()
