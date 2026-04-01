import json
import os
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.exceptions import ImproperlyConfigured

from apps.core.json_utils import (
    validate_ai_registry_payload,
    validate_ai_task_types_payload,
    validate_ai_tools_payload,
    load_json_file,
    validate_change_plan_payload,
    validate_dataset_registry_payload,
    validate_integration_registry_payload,
    validate_role_rules_payload,
    validate_task_brief_payload,
    validate_workflow_rules_payload,
)

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
APP_DISPLAY_NAME = os.environ.get("APP_DISPLAY_NAME", "Local Business Suite")
ALLOWED_HOSTS = [
    host
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host
]
ALLOWED_HOSTS += [
    host
    for host in os.environ.get("DJANGO_INTERNAL_ALLOWED_HOSTS", "web").split(",")
    if host and host not in ALLOWED_HOSTS
]

INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "apps.core",
    "apps.accounts",
    "apps.inventory",
    "apps.workorders",
    "apps.analytics",
    "apps.ai",
    "apps.waiting_list",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.navigation_flags",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db" / "main_vault.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "init_command": (
                "PRAGMA journal_mode=WAL;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA busy_timeout=5000;"
            ),
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "login"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_USE_FINDERS = DEBUG

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOCAL_BUSINESS_ROLE_RULES_FILE = Path(
    os.environ.get("LOCAL_BUSINESS_ROLE_RULES_FILE", BASE_DIR / "config" / "role_rules.json")
)
LOCAL_BUSINESS_WORKFLOW_RULES_FILE = Path(
    os.environ.get("LOCAL_BUSINESS_WORKFLOW_RULES_FILE", BASE_DIR / "config" / "workflow_rules.json")
)
LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE = Path(
    os.environ.get("LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE", BASE_DIR / "config" / "integrations" / "registry.json")
)
LOCAL_BUSINESS_ANALYTICS_DATASETS_FILE = Path(
    os.environ.get("LOCAL_BUSINESS_ANALYTICS_DATASETS_FILE", BASE_DIR / "analytics_store" / "datasets.json")
)
LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE_FILE = Path(
    os.environ.get("LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE_FILE", BASE_DIR / "ai" / "task_briefs" / "template.json")
)
LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE_FILE = Path(
    os.environ.get("LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE_FILE", BASE_DIR / "ai" / "change_plans" / "template.json")
)
LOCAL_BUSINESS_AI_REGISTRY_FILE = Path(
    os.environ.get("LOCAL_BUSINESS_AI_REGISTRY_FILE", BASE_DIR / "config" / "ai" / "registry.json")
)
LOCAL_BUSINESS_AI_TOOLS_FILE = Path(
    os.environ.get("LOCAL_BUSINESS_AI_TOOLS_FILE", BASE_DIR / "config" / "ai" / "tools.json")
)
LOCAL_BUSINESS_AI_TASK_TYPES_FILE = Path(
    os.environ.get("LOCAL_BUSINESS_AI_TASK_TYPES_FILE", BASE_DIR / "config" / "ai" / "task_types.json")
)
LOCAL_BUSINESS_AI_GATEWAY_TOKEN = os.environ.get("LOCAL_BUSINESS_AI_GATEWAY_TOKEN", "dev-ai-gateway-token")
LOCAL_BUSINESS_AGENT_RUNTIME_URL = os.environ.get("LOCAL_BUSINESS_AGENT_RUNTIME_URL", "http://127.0.0.1:8090")
LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT = float(os.environ.get("LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT", "90"))

try:
    LOCAL_BUSINESS_WORKFLOW_RULES = load_json_file(LOCAL_BUSINESS_WORKFLOW_RULES_FILE)
    validate_workflow_rules_payload(LOCAL_BUSINESS_WORKFLOW_RULES)

    LOCAL_BUSINESS_ROLE_RULES = load_json_file(LOCAL_BUSINESS_ROLE_RULES_FILE)
    validate_role_rules_payload(
        LOCAL_BUSINESS_ROLE_RULES,
        workflow_payload=LOCAL_BUSINESS_WORKFLOW_RULES,
    )

    LOCAL_BUSINESS_INTEGRATION_REGISTRY = load_json_file(LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE)
    validate_integration_registry_payload(LOCAL_BUSINESS_INTEGRATION_REGISTRY)

    LOCAL_BUSINESS_ANALYTICS_DATASETS = load_json_file(LOCAL_BUSINESS_ANALYTICS_DATASETS_FILE)
    validate_dataset_registry_payload(LOCAL_BUSINESS_ANALYTICS_DATASETS)

    LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE = load_json_file(LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE_FILE)
    validate_task_brief_payload(LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE)

    LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE = load_json_file(LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE_FILE)
    validate_change_plan_payload(LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE)

    LOCAL_BUSINESS_AI_REGISTRY = load_json_file(LOCAL_BUSINESS_AI_REGISTRY_FILE)
    validate_ai_registry_payload(LOCAL_BUSINESS_AI_REGISTRY)

    LOCAL_BUSINESS_AI_TOOLS = load_json_file(LOCAL_BUSINESS_AI_TOOLS_FILE)
    validate_ai_tools_payload(LOCAL_BUSINESS_AI_TOOLS)

    LOCAL_BUSINESS_AI_TASK_TYPES = load_json_file(LOCAL_BUSINESS_AI_TASK_TYPES_FILE)
    validate_ai_task_types_payload(LOCAL_BUSINESS_AI_TASK_TYPES)
except (OSError, json.JSONDecodeError, ValidationError) as exc:
    raise ImproperlyConfigured(f"Invalid Local Business Suite configuration: {exc}") from exc
