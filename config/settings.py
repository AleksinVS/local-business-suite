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

# Load environment variables from .env file
from dotenv import load_dotenv

env_file = BASE_DIR / ".env"
load_dotenv(env_file)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
APP_DISPLAY_NAME = os.environ.get("APP_DISPLAY_NAME", "Корпоративный портал ВОБ №3")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
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
    "apps.core.middleware.PathInfoDebugMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

APPEND_SLASH = True

# IIS/FastCGI compatibility
FORCE_SCRIPT_NAME = ""

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

# Security flags read from environment (defaults safe for local dev)
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "False") == "True"
SESSION_COOKIE_SECURE = os.environ.get("DJANGO_SESSION_COOKIE_SECURE", "False") == "True"
CSRF_COOKIE_SECURE = os.environ.get("DJANGO_CSRF_COOKIE_SECURE", "False") == "True"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "data" / "logs" / "app.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "django.server": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "apps": {
            "handlers": ["console", "file"],
            "level": "INFO",
        },
        "services": {
            "handlers": ["console", "file"],
            "level": "INFO",
        },
    },
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "db" / "main_vault.sqlite3",
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

AUTH_USER_MODEL = "accounts.User"
DJANGO_AUTH_MODE = os.environ.get("DJANGO_AUTH_MODE", "hybrid").strip().lower()
if DJANGO_AUTH_MODE not in {"local", "ldap", "remote_user", "hybrid"}:
    raise ImproperlyConfigured(
        "DJANGO_AUTH_MODE must be one of: local, ldap, remote_user, hybrid"
    )

# Deployment-specific email override (for users without mail attribute in AD)
AD_EMAIL_DOMAIN_OVERRIDE = os.environ.get("AD_EMAIL_DOMAIN_OVERRIDE", "")

if DJANGO_AUTH_MODE == "local":
    AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
elif DJANGO_AUTH_MODE == "ldap":
    AUTHENTICATION_BACKENDS = ["apps.accounts.ldap_backend.LDAPBackend"]
elif DJANGO_AUTH_MODE == "remote_user":
    AUTHENTICATION_BACKENDS = ["apps.accounts.ldap_backend.RemoteUserLDAPBackend"]
else:
    AUTHENTICATION_BACKENDS = [
        "apps.accounts.ldap_backend.RemoteUserLDAPBackend",
        "apps.accounts.ldap_backend.LDAPBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]

if DJANGO_AUTH_MODE in {"remote_user", "hybrid"}:
    MIDDLEWARE.insert(
        MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware") + 1,
        "django.contrib.auth.middleware.PersistentRemoteUserMiddleware",
    )

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
MEDIA_ROOT = BASE_DIR / "data" / "media"
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

# Contracts configuration
# Default contracts are stored in the 'contracts/' directory (tracked by Git)
# Runtime contracts are stored in 'data/contracts/' (not tracked by Git, editable via UI)
RUNTIME_CONTRACTS_DIR = BASE_DIR / "data" / "contracts"
DEFAULT_CONTRACTS_DIR = BASE_DIR / "contracts"

os.makedirs(RUNTIME_CONTRACTS_DIR / "ai", exist_ok=True)
os.makedirs(RUNTIME_CONTRACTS_DIR / "integrations", exist_ok=True)

def get_contract_path(filename, env_var, sub_dir=None):
    default_path = DEFAULT_CONTRACTS_DIR / (sub_dir + "/" if sub_dir else "") / filename
    runtime_path = RUNTIME_CONTRACTS_DIR / (sub_dir + "/" if sub_dir else "") / filename
    
    # If runtime contract doesn't exist, copy from default (one-time setup)
    if not runtime_path.exists() and default_path.exists():
        import shutil
        shutil.copy(default_path, runtime_path)
        
    return Path(os.environ.get(env_var, runtime_path))

LOCAL_BUSINESS_ROLE_RULES_FILE = get_contract_path("role_rules.json", "LOCAL_BUSINESS_ROLE_RULES_FILE")
LOCAL_BUSINESS_WORKFLOW_RULES_FILE = get_contract_path("workflow_rules.json", "LOCAL_BUSINESS_WORKFLOW_RULES_FILE")
LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE = get_contract_path("registry.json", "LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE", sub_dir="integrations")
LOCAL_BUSINESS_ANALYTICS_DATASETS_FILE = get_contract_path("datasets.json", "LOCAL_BUSINESS_ANALYTICS_DATASETS_FILE", sub_dir="analytics") # Note: analytics in data/analytics/
LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE_FILE = BASE_DIR / "workflow" / "ai_artifacts" / "task_brief_template.json"
LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE_FILE = BASE_DIR / "workflow" / "ai_artifacts" / "template.json"
LOCAL_BUSINESS_AI_REGISTRY_FILE = get_contract_path("registry.json", "LOCAL_BUSINESS_AI_REGISTRY_FILE", sub_dir="ai")
LOCAL_BUSINESS_AI_TOOLS_FILE = get_contract_path("tools.json", "LOCAL_BUSINESS_AI_TOOLS_FILE", sub_dir="ai")
LOCAL_BUSINESS_AI_TASK_TYPES_FILE = get_contract_path("task_types.json", "LOCAL_BUSINESS_AI_TASK_TYPES_FILE", sub_dir="ai")
LOCAL_BUSINESS_AI_MODELS_FILE = get_contract_path("models.json", "LOCAL_BUSINESS_AI_MODELS_FILE", sub_dir="ai")

LOCAL_BUSINESS_AI_GATEWAY_TOKEN = os.environ.get(
    "LOCAL_BUSINESS_AI_GATEWAY_TOKEN", "dev-ai-gateway-token"
)
LOCAL_BUSINESS_AGENT_RUNTIME_URL = os.environ.get(
    "LOCAL_BUSINESS_AGENT_RUNTIME_URL", "http://127.0.0.1:8090"
)
LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT = float(
    os.environ.get("LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT", "90")
)

try:
    LOCAL_BUSINESS_WORKFLOW_RULES = load_json_file(LOCAL_BUSINESS_WORKFLOW_RULES_FILE)
    validate_workflow_rules_payload(LOCAL_BUSINESS_WORKFLOW_RULES)

    LOCAL_BUSINESS_ROLE_RULES = load_json_file(LOCAL_BUSINESS_ROLE_RULES_FILE)
    validate_role_rules_payload(
        LOCAL_BUSINESS_ROLE_RULES,
        workflow_payload=LOCAL_BUSINESS_WORKFLOW_RULES,
    )

    LOCAL_BUSINESS_INTEGRATION_REGISTRY = load_json_file(
        LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE
    )
    validate_integration_registry_payload(LOCAL_BUSINESS_INTEGRATION_REGISTRY)

    LOCAL_BUSINESS_ANALYTICS_DATASETS = load_json_file(
        LOCAL_BUSINESS_ANALYTICS_DATASETS_FILE
    )
    validate_dataset_registry_payload(LOCAL_BUSINESS_ANALYTICS_DATASETS)

    LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE = load_json_file(
        LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE_FILE
    )
    validate_task_brief_payload(LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE)

    LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE = load_json_file(
        LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE_FILE
    )
    validate_change_plan_payload(LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE)

    LOCAL_BUSINESS_AI_REGISTRY = load_json_file(LOCAL_BUSINESS_AI_REGISTRY_FILE)
    validate_ai_registry_payload(LOCAL_BUSINESS_AI_REGISTRY)

    LOCAL_BUSINESS_AI_TOOLS = load_json_file(LOCAL_BUSINESS_AI_TOOLS_FILE)
    validate_ai_tools_payload(LOCAL_BUSINESS_AI_TOOLS)

    LOCAL_BUSINESS_AI_TASK_TYPES = load_json_file(LOCAL_BUSINESS_AI_TASK_TYPES_FILE)
    validate_ai_task_types_payload(LOCAL_BUSINESS_AI_TASK_TYPES)

    LOCAL_BUSINESS_AI_MODELS = load_json_file(LOCAL_BUSINESS_AI_MODELS_FILE)
except (OSError, json.JSONDecodeError, ValidationError) as exc:
    raise ImproperlyConfigured(
        f"Invalid Корпоративный портал ВОБ №3 configuration: {exc}"
    ) from exc
