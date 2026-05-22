from django.conf import settings


CHAT_DB_MODELS = {
    "agentactionlog",
    "chatattachment",
    "chatmessage",
    "chatsession",
    "pendingaction",
}


class LocalBusinessDatabaseRouter:
    """Routes separated runtime domains to their SQLite databases."""

    app_label_to_database = {
        "analytics": "analytics_control",
        "memory": "knowledge_meta",
    }

    def db_for_read(self, model, **hints):
        return self._database_for_model(model)

    def db_for_write(self, model, **hints):
        return self._database_for_model(model)

    def allow_relation(self, obj1, obj2, **hints):
        dbs = {"default", "chat", "knowledge_meta", "analytics_control"}
        if obj1._state.db in dbs and obj2._state.db in dbs:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if not getattr(settings, "LOCAL_BUSINESS_DB_SPLIT_ENABLED", True):
            return db == "default"
        if app_label == "ai" and model_name:
            target_db = "chat" if model_name.lower() in CHAT_DB_MODELS else "default"
            return db == target_db

        target_db = self.app_label_to_database.get(app_label, "default")
        return db == target_db

    def _database_for_model(self, model):
        if not getattr(settings, "LOCAL_BUSINESS_DB_SPLIT_ENABLED", True):
            return None
        app_label = model._meta.app_label
        model_name = model._meta.model_name
        if app_label == "ai" and model_name in CHAT_DB_MODELS:
            return "chat"
        return self.app_label_to_database.get(app_label) or "default"
