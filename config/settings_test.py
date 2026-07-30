"""Настройки, используемые только автоматическими тестами.

Production-настройки импортируются без изменения, после чего дорогие
реализации и пути артефактов заменяются безопасными тестовыми эквивалентами.
"""

from copy import deepcopy

from .settings import *  # noqa: F403


PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
MEDIA_ROOT = BASE_DIR / ".local" / "test-media"  # noqa: F405

# Django по умолчанию использует SQLite in-memory test database, которую
# невозможно переиспользовать между отдельными pytest-процессами. Локальный
# файл в .local/ делает --reuse-db рабочим; pytest-django добавляет отдельные
# suffix-имена для xdist workers.
DATABASES = deepcopy(DATABASES)  # noqa: F405
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"]["TEST"] = {
        **DATABASES["default"].get("TEST", {}),
        "NAME": BASE_DIR / ".local" / "test-default.sqlite3",  # noqa: F405
    }
