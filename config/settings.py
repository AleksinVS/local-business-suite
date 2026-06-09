import json
import os
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.exceptions import ImproperlyConfigured

from apps.core.json_utils import (
    validate_analytics_business_facts_payload,
    validate_analytics_dedup_rules_payload,
    validate_analytics_diagnostic_playbooks_payload,
    validate_analytics_metrics_payload,
    validate_analytics_monitors_payload,
    validate_analytics_retention_profiles_payload,
    validate_analytics_scope_rules_payload,
    validate_analytics_sources_payload,
    validate_analytics_workflow_routes_payload,
    validate_ai_registry_payload,
    validate_ai_chat_settings_payload,
    validate_ai_task_types_payload,
    validate_ai_tools_payload,
    load_json_file,
    validate_change_plan_payload,
    validate_dataset_registry_payload,
    validate_integration_registry_payload,
    validate_memory_profiles_payload,
    validate_memory_claims_policy_payload,
    validate_memory_graph_schema_payload,
    validate_memory_file_organization_profiles_payload,
    validate_memory_ingestion_profiles_payload,
    validate_memory_retrieval_budget_payload,
    validate_memory_routing_payload,
    validate_memory_sources_payload,
    validate_memory_trust_policy_payload,
    validate_role_rules_payload,
    validate_task_brief_payload,
    validate_workorder_status_colors_payload,
    validate_workflow_rules_payload,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
for runtime_dir in (
    DATA_DIR / "db",
    DATA_DIR / "media",
    DATA_DIR / "logs",
    DATA_DIR / "contracts",
    DATA_DIR / "knowledge_repo",
    DATA_DIR / "queues",
    DATA_DIR / "indexes" / "fulltext",
    DATA_DIR / "indexes" / "vector",
    DATA_DIR / "indexes" / "graph",
    DATA_DIR / "processing" / "raw_quarantine",
    DATA_DIR / "processing" / "safe_work",
    DATA_DIR / "processing" / "extraction_packets",
    DATA_DIR / "processing" / "cleanup_manifests",
    DATA_DIR / "cache",
    DATA_DIR / "analytics" / "duckdb",
):
    runtime_dir.mkdir(parents=True, exist_ok=True)

# Load environment variables from .env file
from dotenv import load_dotenv

env_file = BASE_DIR / ".env"
load_dotenv(env_file)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
DJANGO_ENV = os.environ.get("DJANGO_ENV", "development").strip().lower()
if DJANGO_ENV not in {"development", "production"}:
    raise ImproperlyConfigured("DJANGO_ENV must be one of: development, production")
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
    "apps.notifications",
    "apps.analytics",
    "apps.ai",
    "apps.memory",
    "apps.settings_center",
    "apps.waiting_list",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.core.middleware.PathInfoDebugMiddleware",
    "django.middleware.common.CommonMiddleware",
    "apps.core.performance.PerformanceMetricsMiddleware",
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
                "apps.ai.context_processors.sidebar_ai_chat",
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
            "filename": DATA_DIR / "logs" / "app.log",
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

LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED = os.environ.get(
    "LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
LOCAL_BUSINESS_PERFORMANCE_METRICS_PATH = Path(
    os.environ.get(
        "LOCAL_BUSINESS_PERFORMANCE_METRICS_PATH",
        DATA_DIR / "logs" / "performance_events.jsonl",
    )
)
LOCAL_BUSINESS_PERFORMANCE_METRICS_SAMPLE_RATE = float(
    os.environ.get("LOCAL_BUSINESS_PERFORMANCE_METRICS_SAMPLE_RATE", "1.0")
)
if not 0 <= LOCAL_BUSINESS_PERFORMANCE_METRICS_SAMPLE_RATE <= 1:
    raise ImproperlyConfigured("LOCAL_BUSINESS_PERFORMANCE_METRICS_SAMPLE_RATE must be between 0 and 1")
LOCAL_BUSINESS_PERFORMANCE_METRICS_EXCLUDE_PREFIXES = tuple(
    prefix.strip()
    for prefix in os.environ.get(
        "LOCAL_BUSINESS_PERFORMANCE_METRICS_EXCLUDE_PREFIXES",
        "/static/,/media/,/favicon.",
    ).split(",")
    if prefix.strip()
)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db" / "main_vault.sqlite3",
        "OPTIONS": {
            "timeout": 20,
        },
    },
    "chat": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db" / "chat.sqlite3",
        "OPTIONS": {
            "timeout": 20,
        },
    },
    "knowledge_meta": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db" / "knowledge_meta.sqlite3",
        "OPTIONS": {
            "timeout": 20,
        },
    },
    "analytics_control": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db" / "analytics_control.sqlite3",
        "OPTIONS": {
            "timeout": 20,
        },
    }
}

DATABASE_ROUTERS = ["apps.core.db_routers.LocalBusinessDatabaseRouter"]


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
        "apps.accounts.middleware.ManualAuthAwareRemoteUserMiddleware",
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
MEDIA_ROOT = DATA_DIR / "media"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_USE_FINDERS = DEBUG
WHITENOISE_MANIFEST_STRICT = not DEBUG

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Contracts configuration
# Default contracts are stored in the 'contracts/' directory (tracked by Git)
# Runtime contracts are stored in 'data/contracts/' (not tracked by Git, editable via UI)
RUNTIME_CONTRACTS_DIR = DATA_DIR / "contracts"
DEFAULT_CONTRACTS_DIR = BASE_DIR / "contracts"

os.makedirs(RUNTIME_CONTRACTS_DIR / "ai", exist_ok=True)
os.makedirs(RUNTIME_CONTRACTS_DIR / "integrations", exist_ok=True)
os.makedirs(RUNTIME_CONTRACTS_DIR / "analytics", exist_ok=True)

def get_contract_path(filename, env_var, sub_dir=None):
    default_path = DEFAULT_CONTRACTS_DIR / (sub_dir or "") / filename
    runtime_path = RUNTIME_CONTRACTS_DIR / (sub_dir or "") / filename
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    
    # If runtime contract doesn't exist, copy from default (one-time setup)
    if not runtime_path.exists() and default_path.exists():
        import shutil
        shutil.copy(default_path, runtime_path)
        
    override = os.environ.get(env_var, "").strip()
    return Path(override) if override else runtime_path

LOCAL_BUSINESS_ROLE_RULES_FILE = get_contract_path("role_rules.json", "LOCAL_BUSINESS_ROLE_RULES_FILE")
LOCAL_BUSINESS_WORKFLOW_RULES_FILE = get_contract_path("workflow_rules.json", "LOCAL_BUSINESS_WORKFLOW_RULES_FILE")
LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE = get_contract_path("workorder_status_colors.json", "LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE")
LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE = get_contract_path("registry.json", "LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE", sub_dir="integrations")
LOCAL_BUSINESS_ANALYTICS_DATASETS_FILE = get_contract_path("datasets.json", "LOCAL_BUSINESS_ANALYTICS_DATASETS_FILE", sub_dir="analytics") # Note: analytics in data/analytics/
LOCAL_BUSINESS_ANALYTICS_SOURCES_FILE = get_contract_path("sources.json", "LOCAL_BUSINESS_ANALYTICS_SOURCES_FILE", sub_dir="analytics")
LOCAL_BUSINESS_ANALYTICS_SCOPE_RULES_FILE = get_contract_path("analysis_scope_rules.json", "LOCAL_BUSINESS_ANALYTICS_SCOPE_RULES_FILE", sub_dir="analytics")
LOCAL_BUSINESS_ANALYTICS_BUSINESS_FACTS_FILE = get_contract_path("business_facts.json", "LOCAL_BUSINESS_ANALYTICS_BUSINESS_FACTS_FILE", sub_dir="analytics")
LOCAL_BUSINESS_ANALYTICS_METRICS_FILE = get_contract_path("metrics.json", "LOCAL_BUSINESS_ANALYTICS_METRICS_FILE", sub_dir="analytics")
LOCAL_BUSINESS_ANALYTICS_MONITORS_FILE = get_contract_path("monitors.json", "LOCAL_BUSINESS_ANALYTICS_MONITORS_FILE", sub_dir="analytics")
LOCAL_BUSINESS_ANALYTICS_DIAGNOSTIC_PLAYBOOKS_FILE = get_contract_path("diagnostic_playbooks.json", "LOCAL_BUSINESS_ANALYTICS_DIAGNOSTIC_PLAYBOOKS_FILE", sub_dir="analytics")
LOCAL_BUSINESS_ANALYTICS_WORKFLOW_ROUTES_FILE = get_contract_path("workflow_routes.json", "LOCAL_BUSINESS_ANALYTICS_WORKFLOW_ROUTES_FILE", sub_dir="analytics")
LOCAL_BUSINESS_ANALYTICS_DEDUP_RULES_FILE = get_contract_path("dedup_rules.json", "LOCAL_BUSINESS_ANALYTICS_DEDUP_RULES_FILE", sub_dir="analytics")
LOCAL_BUSINESS_ANALYTICS_RETENTION_PROFILES_FILE = get_contract_path("retention_profiles.json", "LOCAL_BUSINESS_ANALYTICS_RETENTION_PROFILES_FILE", sub_dir="analytics")
LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE_FILE = BASE_DIR / "workflow" / "ai_artifacts" / "task_brief_template.json"
LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE_FILE = BASE_DIR / "workflow" / "ai_artifacts" / "template.json"
LOCAL_BUSINESS_AI_REGISTRY_FILE = get_contract_path("registry.json", "LOCAL_BUSINESS_AI_REGISTRY_FILE", sub_dir="ai")
LOCAL_BUSINESS_AI_TOOLS_FILE = get_contract_path("tools.json", "LOCAL_BUSINESS_AI_TOOLS_FILE", sub_dir="ai")
LOCAL_BUSINESS_AI_TASK_TYPES_FILE = get_contract_path("task_types.json", "LOCAL_BUSINESS_AI_TASK_TYPES_FILE", sub_dir="ai")
LOCAL_BUSINESS_AI_MODELS_FILE = get_contract_path("models.json", "LOCAL_BUSINESS_AI_MODELS_FILE", sub_dir="ai")
LOCAL_BUSINESS_AI_CHAT_SETTINGS_FILE = get_contract_path("chat_settings.json", "LOCAL_BUSINESS_AI_CHAT_SETTINGS_FILE", sub_dir="ai")
LOCAL_BUSINESS_MEMORY_SOURCES_FILE = get_contract_path("memory_sources.json", "LOCAL_BUSINESS_MEMORY_SOURCES_FILE", sub_dir="ai")
LOCAL_BUSINESS_MEMORY_PROFILES_FILE = get_contract_path("memory_profiles.json", "LOCAL_BUSINESS_MEMORY_PROFILES_FILE", sub_dir="ai")
LOCAL_BUSINESS_MEMORY_ROUTING_FILE = get_contract_path("memory_routing.json", "LOCAL_BUSINESS_MEMORY_ROUTING_FILE", sub_dir="ai")
LOCAL_BUSINESS_MEMORY_TRUST_POLICY_FILE = get_contract_path(
    "memory_trust_policy.json",
    "LOCAL_BUSINESS_MEMORY_TRUST_POLICY_FILE",
    sub_dir="ai",
)
LOCAL_BUSINESS_MEMORY_CLAIMS_POLICY_FILE = get_contract_path(
    "memory_claims_policy.json",
    "LOCAL_BUSINESS_MEMORY_CLAIMS_POLICY_FILE",
    sub_dir="ai",
)
LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET_FILE = get_contract_path(
    "memory_retrieval_budget.json",
    "LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET_FILE",
    sub_dir="ai",
)
LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES_FILE = get_contract_path(
    "memory_ingestion_profiles.json",
    "LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES_FILE",
    sub_dir="ai",
)
LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES_FILE = get_contract_path(
    "memory_file_organization_profiles.json",
    "LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES_FILE",
    sub_dir="ai",
)
LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA_FILE = get_contract_path(
    "memory_graph_schema.json",
    "LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA_FILE",
    sub_dir="ai",
)
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND = os.environ.get(
    "LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND",
    "sqlite",
)
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH = Path(
    os.environ.get(
        "LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH",
        DATA_DIR / "memory" / "queues" / "external_connectors.sqlite3",
    )
)
LOCAL_BUSINESS_DB_SPLIT_ENABLED = os.environ.get("LOCAL_BUSINESS_DB_SPLIT_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LOCAL_BUSINESS_KNOWLEDGE_REPO_DIR = Path(
    os.environ.get("LOCAL_BUSINESS_KNOWLEDGE_REPO_DIR", DATA_DIR / "knowledge_repo")
)
LOCAL_BUSINESS_KNOWLEDGE_WRITER_QUEUE_PATH = Path(
    os.environ.get("LOCAL_BUSINESS_KNOWLEDGE_WRITER_QUEUE_PATH", DATA_DIR / "queues" / "knowledge_writer.sqlite3")
)
LOCAL_BUSINESS_SEARCH_INDEX_PATH = Path(
    os.environ.get("LOCAL_BUSINESS_SEARCH_INDEX_PATH", DATA_DIR / "indexes" / "fulltext" / "search.sqlite3")
)
LOCAL_BUSINESS_MEMORY_VECTOR_BACKEND = os.environ.get("LOCAL_BUSINESS_MEMORY_VECTOR_BACKEND", "lancedb").strip().lower()
if LOCAL_BUSINESS_MEMORY_VECTOR_BACKEND not in {"disabled", "lancedb", "enabled"}:
    raise ImproperlyConfigured("LOCAL_BUSINESS_MEMORY_VECTOR_BACKEND must be one of: disabled, lancedb, enabled")
LOCAL_BUSINESS_MEMORY_EMBEDDING_PROFILE = os.environ.get("LOCAL_BUSINESS_MEMORY_EMBEDDING_PROFILE", "local_hash_test_v1").strip()
LOCAL_BUSINESS_MEMORY_TEXT_EXTRACTION_LIMITS = {
    "max_text_bytes": int(os.environ.get("LOCAL_BUSINESS_MEMORY_TEXT_MAX_BYTES", "1000000")),
    "max_sheets": int(os.environ.get("LOCAL_BUSINESS_MEMORY_TEXT_MAX_SHEETS", "20")),
    "max_rows": int(os.environ.get("LOCAL_BUSINESS_MEMORY_TEXT_MAX_ROWS", "5000")),
    "max_cells": int(os.environ.get("LOCAL_BUSINESS_MEMORY_TEXT_MAX_CELLS", "100000")),
    "max_cell_chars": int(os.environ.get("LOCAL_BUSINESS_MEMORY_TEXT_MAX_CELL_CHARS", "2000")),
}
LOCAL_BUSINESS_PROCESSING_DIR = Path(
    os.environ.get("LOCAL_BUSINESS_PROCESSING_DIR", DATA_DIR / "processing")
)
LOCAL_BUSINESS_PROCESSING_RETENTION_DAYS = int(os.environ.get("LOCAL_BUSINESS_PROCESSING_RETENTION_DAYS", "7"))

LOCAL_BUSINESS_AI_GATEWAY_TOKEN = os.environ.get(
    "LOCAL_BUSINESS_AI_GATEWAY_TOKEN", "dev-ai-gateway-token"
)
LOCAL_BUSINESS_AGENT_RUNTIME_URL = os.environ.get(
    "LOCAL_BUSINESS_AGENT_RUNTIME_URL", "http://127.0.0.1:8090"
)
LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT = float(
    os.environ.get("LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT", "90")
)
LOCAL_BUSINESS_COPILOTKIT_ENABLED = os.environ.get(
    "LOCAL_BUSINESS_COPILOTKIT_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
_LOCAL_BUSINESS_AI_UI_DRIVER_ENV = os.environ.get("LOCAL_BUSINESS_AI_UI_DRIVER", "").strip().lower()
LOCAL_BUSINESS_AI_UI_DRIVER_EXPLICIT = bool(_LOCAL_BUSINESS_AI_UI_DRIVER_ENV)
LOCAL_BUSINESS_AI_UI_DRIVER = _LOCAL_BUSINESS_AI_UI_DRIVER_ENV
if not LOCAL_BUSINESS_AI_UI_DRIVER and LOCAL_BUSINESS_COPILOTKIT_ENABLED:
    LOCAL_BUSINESS_AI_UI_DRIVER = "copilotkit"
if not LOCAL_BUSINESS_AI_UI_DRIVER:
    LOCAL_BUSINESS_AI_UI_DRIVER = "legacy"
if LOCAL_BUSINESS_AI_UI_DRIVER not in {"legacy", "copilotkit", "native"}:
    raise ImproperlyConfigured(
        "LOCAL_BUSINESS_AI_UI_DRIVER must be one of: legacy, copilotkit, native"
    )
LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION = os.environ.get(
    "LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION", "1.0"
)
LOCAL_BUSINESS_AI_UI_AGUI_PROFILE = os.environ.get(
    "LOCAL_BUSINESS_AI_UI_AGUI_PROFILE", "ag-ui@0.0.55"
)
LOCAL_BUSINESS_AI_UI_ACTOR_TOKEN_TTL_SECONDS = int(
    os.environ.get(
        "LOCAL_BUSINESS_AI_UI_ACTOR_TOKEN_TTL_SECONDS",
        os.environ.get("LOCAL_BUSINESS_COPILOTKIT_ACTOR_TOKEN_TTL_SECONDS", "900"),
    )
)
LOCAL_BUSINESS_AGENT_RUNTIME_AG_UI_URL = os.environ.get(
    "LOCAL_BUSINESS_AGENT_RUNTIME_AG_UI_URL",
    f"{LOCAL_BUSINESS_AGENT_RUNTIME_URL.rstrip('/')}/ag-ui",
)
LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL = os.environ.get(
    "LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL", "/copilotkit"
)
LOCAL_BUSINESS_COPILOTKIT_AGENT_ID = os.environ.get(
    "LOCAL_BUSINESS_COPILOTKIT_AGENT_ID", "local_business"
)
LOCAL_BUSINESS_COPILOTKIT_ACTOR_TOKEN_TTL_SECONDS = int(
    os.environ.get("LOCAL_BUSINESS_COPILOTKIT_ACTOR_TOKEN_TTL_SECONDS", "900")
)
GUNICORN_TIMEOUT = int(os.environ.get("GUNICORN_TIMEOUT", "600"))
GUNICORN_GRACEFUL_TIMEOUT = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
LOCAL_BUSINESS_AI_PENDING_ACTION_TTL_SECONDS = int(
    os.environ.get("LOCAL_BUSINESS_AI_PENDING_ACTION_TTL_SECONDS", "900")
)
LOCAL_BUSINESS_SECRET_VAULT_BASE_URL = os.environ.get("LOCAL_BUSINESS_SECRET_VAULT_BASE_URL", "")
SETTINGS_CENTER_ENABLED = os.environ.get("SETTINGS_CENTER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
SETTINGS_CENTER_ENV_APPLY_MODE = os.environ.get("SETTINGS_CENTER_ENV_APPLY_MODE", "proposal").strip().lower()
if SETTINGS_CENTER_ENV_APPLY_MODE not in {"read_only", "proposal", "local_file"}:
    raise ImproperlyConfigured(
        "SETTINGS_CENTER_ENV_APPLY_MODE must be one of: read_only, proposal, local_file"
    )
SETTINGS_CENTER_ENV_FILE = BASE_DIR / os.environ.get("SETTINGS_CENTER_ENV_FILE", ".env")
SETTINGS_CENTER_ENV_PROPOSAL_DIR = Path(
    os.environ.get(
        "SETTINGS_CENTER_ENV_PROPOSAL_DIR",
        DATA_DIR / "settings_center" / "env_proposals",
    )
)
SETTINGS_CENTER_HELP_AI_ENABLED = os.environ.get(
    "SETTINGS_CENTER_HELP_AI_ENABLED", "true"
).strip().lower() in {"1", "true", "yes", "on"}
SETTINGS_CENTER_HELP_MODEL_PROFILE = os.environ.get(
    "SETTINGS_CENTER_HELP_MODEL_PROFILE", "local_admin_help_v1"
)
SETTINGS_CENTER_HELP_MAX_CONTEXT_CHARS = int(
    os.environ.get("SETTINGS_CENTER_HELP_MAX_CONTEXT_CHARS", "6000")
)
SETTINGS_CENTER_AUDIT_RETENTION_DAYS = int(
    os.environ.get("SETTINGS_CENTER_AUDIT_RETENTION_DAYS", "365")
)
ACCOUNTS_AD_LINK_ENABLED = os.environ.get("ACCOUNTS_AD_LINK_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
ACCOUNTS_AD_LINK_MODE = os.environ.get("ACCOUNTS_AD_LINK_MODE", "manual").strip().lower()
ACCOUNTS_AD_GROUP_ROLE_SYNC = os.environ.get("ACCOUNTS_AD_GROUP_ROLE_SYNC", "false").strip().lower() in {"1", "true", "yes", "on"}
MEMORY_ACL_INHERITANCE_ENABLED = os.environ.get("MEMORY_ACL_INHERITANCE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
MEMORY_ACL_FAIL_CLOSED = os.environ.get("MEMORY_ACL_FAIL_CLOSED", "true").strip().lower() in {"1", "true", "yes", "on"}
MEMORY_ACL_UNRESOLVED_POLICY = os.environ.get("MEMORY_ACL_UNRESOLVED_POLICY", "block").strip().lower()
if MEMORY_ACL_UNRESOLVED_POLICY not in {"block", "admin_only", "fallback_scope_rule"}:
    raise ImproperlyConfigured(
        "MEMORY_ACL_UNRESOLVED_POLICY must be one of: block, admin_only, fallback_scope_rule"
    )
MEMORY_ACL_GROUP_NESTING_DEPTH = int(os.environ.get("MEMORY_ACL_GROUP_NESTING_DEPTH", "5"))
MEMORY_ACL_CACHE_TTL_SECONDS = int(os.environ.get("MEMORY_ACL_CACHE_TTL_SECONDS", "3600"))

if DJANGO_ENV == "production":
    unsafe_secret_keys = {"", "dev-only-secret-key", "change-me"}
    unsafe_gateway_tokens = {"", "dev-ai-gateway-token", "change-me"}
    if DEBUG:
        raise ImproperlyConfigured("DJANGO_DEBUG must be 0 when DJANGO_ENV=production")
    if SECRET_KEY in unsafe_secret_keys:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set to a non-default value in production")
    if LOCAL_BUSINESS_AI_GATEWAY_TOKEN in unsafe_gateway_tokens:
        raise ImproperlyConfigured(
            "LOCAL_BUSINESS_AI_GATEWAY_TOKEN must be set to a non-default value in production"
        )
    min_stream_timeout = int(LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT) + 30
    if GUNICORN_TIMEOUT < min_stream_timeout:
        raise ImproperlyConfigured(
            "GUNICORN_TIMEOUT must be at least LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT + 30 seconds "
            f"for AI streaming requests. Current GUNICORN_TIMEOUT={GUNICORN_TIMEOUT}, "
            f"required>={min_stream_timeout}."
        )

try:
    LOCAL_BUSINESS_WORKFLOW_RULES = load_json_file(LOCAL_BUSINESS_WORKFLOW_RULES_FILE)
    validate_workflow_rules_payload(LOCAL_BUSINESS_WORKFLOW_RULES)

    LOCAL_BUSINESS_ROLE_RULES = load_json_file(LOCAL_BUSINESS_ROLE_RULES_FILE)
    validate_role_rules_payload(
        LOCAL_BUSINESS_ROLE_RULES,
        workflow_payload=LOCAL_BUSINESS_WORKFLOW_RULES,
    )

    LOCAL_BUSINESS_WORKORDER_STATUS_COLORS = load_json_file(LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE)
    validate_workorder_status_colors_payload(
        LOCAL_BUSINESS_WORKORDER_STATUS_COLORS,
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
    LOCAL_BUSINESS_ANALYTICS_SOURCES = load_json_file(LOCAL_BUSINESS_ANALYTICS_SOURCES_FILE)
    validate_analytics_sources_payload(LOCAL_BUSINESS_ANALYTICS_SOURCES)
    LOCAL_BUSINESS_ANALYTICS_SCOPE_RULES = load_json_file(LOCAL_BUSINESS_ANALYTICS_SCOPE_RULES_FILE)
    validate_analytics_scope_rules_payload(LOCAL_BUSINESS_ANALYTICS_SCOPE_RULES)
    LOCAL_BUSINESS_ANALYTICS_BUSINESS_FACTS = load_json_file(LOCAL_BUSINESS_ANALYTICS_BUSINESS_FACTS_FILE)
    validate_analytics_business_facts_payload(LOCAL_BUSINESS_ANALYTICS_BUSINESS_FACTS)
    LOCAL_BUSINESS_ANALYTICS_METRICS = load_json_file(LOCAL_BUSINESS_ANALYTICS_METRICS_FILE)
    validate_analytics_metrics_payload(LOCAL_BUSINESS_ANALYTICS_METRICS)
    LOCAL_BUSINESS_ANALYTICS_MONITORS = load_json_file(LOCAL_BUSINESS_ANALYTICS_MONITORS_FILE)
    validate_analytics_monitors_payload(LOCAL_BUSINESS_ANALYTICS_MONITORS)
    LOCAL_BUSINESS_ANALYTICS_DIAGNOSTIC_PLAYBOOKS = load_json_file(LOCAL_BUSINESS_ANALYTICS_DIAGNOSTIC_PLAYBOOKS_FILE)
    validate_analytics_diagnostic_playbooks_payload(LOCAL_BUSINESS_ANALYTICS_DIAGNOSTIC_PLAYBOOKS)
    LOCAL_BUSINESS_ANALYTICS_WORKFLOW_ROUTES = load_json_file(LOCAL_BUSINESS_ANALYTICS_WORKFLOW_ROUTES_FILE)
    validate_analytics_workflow_routes_payload(LOCAL_BUSINESS_ANALYTICS_WORKFLOW_ROUTES)
    LOCAL_BUSINESS_ANALYTICS_DEDUP_RULES = load_json_file(LOCAL_BUSINESS_ANALYTICS_DEDUP_RULES_FILE)
    validate_analytics_dedup_rules_payload(LOCAL_BUSINESS_ANALYTICS_DEDUP_RULES)
    LOCAL_BUSINESS_ANALYTICS_RETENTION_PROFILES = load_json_file(LOCAL_BUSINESS_ANALYTICS_RETENTION_PROFILES_FILE)
    validate_analytics_retention_profiles_payload(LOCAL_BUSINESS_ANALYTICS_RETENTION_PROFILES)

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

    LOCAL_BUSINESS_AI_CHAT_SETTINGS = load_json_file(LOCAL_BUSINESS_AI_CHAT_SETTINGS_FILE)
    validate_ai_chat_settings_payload(LOCAL_BUSINESS_AI_CHAT_SETTINGS)

    LOCAL_BUSINESS_MEMORY_PROFILES = load_json_file(LOCAL_BUSINESS_MEMORY_PROFILES_FILE)
    validate_memory_profiles_payload(LOCAL_BUSINESS_MEMORY_PROFILES)

    LOCAL_BUSINESS_MEMORY_ROUTING = load_json_file(LOCAL_BUSINESS_MEMORY_ROUTING_FILE)
    validate_memory_routing_payload(LOCAL_BUSINESS_MEMORY_ROUTING)

    LOCAL_BUSINESS_MEMORY_TRUST_POLICY = load_json_file(LOCAL_BUSINESS_MEMORY_TRUST_POLICY_FILE)
    validate_memory_trust_policy_payload(LOCAL_BUSINESS_MEMORY_TRUST_POLICY)

    LOCAL_BUSINESS_MEMORY_CLAIMS_POLICY = load_json_file(LOCAL_BUSINESS_MEMORY_CLAIMS_POLICY_FILE)
    validate_memory_claims_policy_payload(LOCAL_BUSINESS_MEMORY_CLAIMS_POLICY)

    LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET = load_json_file(LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET_FILE)
    validate_memory_retrieval_budget_payload(LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET)

    LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES = load_json_file(LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES_FILE)
    validate_memory_ingestion_profiles_payload(LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES)

    LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES = load_json_file(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES_FILE)
    validate_memory_file_organization_profiles_payload(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES)

    LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA = load_json_file(LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA_FILE)
    validate_memory_graph_schema_payload(LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA)

    LOCAL_BUSINESS_MEMORY_SOURCES = load_json_file(LOCAL_BUSINESS_MEMORY_SOURCES_FILE)
    validate_memory_sources_payload(
        LOCAL_BUSINESS_MEMORY_SOURCES,
        profiles_payload=LOCAL_BUSINESS_MEMORY_PROFILES,
        routing_payload=LOCAL_BUSINESS_MEMORY_ROUTING,
        ingestion_profiles_payload=LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES,
    )
except (OSError, json.JSONDecodeError, ValidationError) as exc:
    raise ImproperlyConfigured(
        f"Invalid Корпоративный портал ВОБ №3 configuration: {exc}"
    ) from exc
