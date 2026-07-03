class LocalBusinessDatabaseRouter:
    """Legacy router for the archived SQLite split.

    The main repository now targets a single ``default`` database. This
    router is kept only so old deployment settings fail soft while
    migration tooling moves data from archived SQLite files.
    """

    def db_for_read(self, model, **hints):
        return None

    def db_for_write(self, model, **hints):
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if obj1._state.db == obj2._state.db == "default":
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == "default"

    def _database_for_model(self, model):
        return None
