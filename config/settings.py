import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

from apps.core.json_utils import load_json_file

BASE_DIR = Path(__file__).resolve().parent.parent
# Расположение изменяемого runtime-состояния. По умолчанию — ``<repo>/data``
# (расположение НЕ меняется), переменная окружения позволяет вынести данные в
# другой каталог для деплоя или изолированного теста.
#
# ВАЖНО: импорт настроек больше НЕ создаёт эти каталоги и не копирует дефолты.
# Первичную подготовку runtime выполняет идемпотентная команда
# ``python manage.py bootstrap_runtime`` (см. ADR-0031, README и
# docs/deployment/DEPLOYMENT.md). Побочная запись на диск при импорте конфигурации
# ломала read-only и параллельные запуски и заставляла каждую manage.py-команду
# платить за создание каталогов и копирование файлов.
DATA_DIR = Path(os.environ.get("LOCAL_BUSINESS_DATA_DIR", BASE_DIR / "data"))

# Load environment variables from .env file
from dotenv import load_dotenv

env_file = BASE_DIR / ".env"
load_dotenv(env_file)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
DJANGO_ENV = os.environ.get("DJANGO_ENV", "development").strip().lower()
if DJANGO_ENV not in {"development", "production"}:
    raise ImproperlyConfigured("DJANGO_ENV must be one of: development, production")

TRUE_VALUES = {"1", "true", "yes", "on"}


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in TRUE_VALUES


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
    "apps.filehub",
    "apps.settings_center",
    "apps.waiting_list",
]

# IIS-совместимый отладочный контур (PATH_INFO-фикс для IIS/FastCGI, см.
# apps/core/middleware.py:PathInfoDebugMiddleware, плюс staff-only debug_request в
# apps/core/urls.py) включается только явным флагом деплоя. По умолчанию выключен:
# на Linux/Docker-хосте PATH_INFO не искажается, и безусловное включение раньше
# приводило к жёстко зашитому Windows-пути и записи файла на каждый запрос даже
# вне IIS (см. docs/deployment/IIS_SSO.md).
LOCAL_BUSINESS_IIS_COMPAT_ENABLED = env_bool("LOCAL_BUSINESS_IIS_COMPAT_ENABLED", False)


def build_middleware(iis_compat_enabled):
    """Собирает список MIDDLEWARE.

    Вынесено в отдельную функцию (а не встроено в условие внутри списка), чтобы
    решение "добавлять ли PathInfoDebugMiddleware" можно было проверить тестом
    напрямую по значению флага, не полагаясь на runtime ``override_settings``
    (``MIDDLEWARE`` собирается один раз при импорте settings).
    """

    middleware = [
        "django.middleware.security.SecurityMiddleware",
        "whitenoise.middleware.WhiteNoiseMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
    ]
    if iis_compat_enabled:
        middleware.append("apps.core.middleware.PathInfoDebugMiddleware")
    middleware += [
        "django.middleware.common.CommonMiddleware",
        "apps.core.performance.PerformanceMetricsMiddleware",
        "django_htmx.middleware.HtmxMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
    ]
    return middleware


MIDDLEWARE = build_middleware(LOCAL_BUSINESS_IIS_COMPAT_ENABLED)

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

# Security flags read from environment (defaults safe for local dev).
# env_bool — единый разбор булевых флагов ({"1","true","yes","on"}); он принимает
# документированные в DEPLOYMENT.md значения True/False и заодно устраняет прежний
# строгий `== "True"`, который молча игнорировал, например, `=1`.
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", False)

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
        # delay=True — файл открывается лениво, при первой записи, а не при
        # применении LOGGING в django.setup(). Это обязательное следствие выноса
        # bootstrap-побочек из импорта settings: раньше каталог data/logs/
        # создавался на импорте, теперь его создаёт `bootstrap_runtime`, поэтому
        # конфигурация логирования не должна требовать существующего каталога до
        # bootstrap (иначе любая manage.py-команда в чистой среде падала бы на
        # "Unable to configure handler 'file'").
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": DATA_DIR / "logs" / "app.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
            "delay": True,
        },
        # IIS PATH_INFO-фикс: отдельный файл вместо жёстко зашитого Windows-пути
        # и open() внутри middleware (см. apps/core/middleware.py). delay=True —
        # файл не создаётся, пока логгер ниже не пропустит хотя бы одну запись
        # (по умолчанию его уровень WARNING выше, чем INFO, которым пишет
        # middleware, поэтому при отключённом подробном логировании файла нет).
        "iis_path_debug_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": DATA_DIR / "logs" / "iis_path_debug.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
            "formatter": "verbose",
            "delay": True,
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
        # Подробность IIS PATH_INFO-диагностики управляется уровнем логгера, а не
        # отдельным вторым env-флагом: по умолчанию WARNING гасит INFO-записи
        # middleware (тихо, файл не создаётся); для диагностики на IIS-стенде
        # временно поднимите уровень через LOCAL_BUSINESS_IIS_PATH_DEBUG_LOG_LEVEL=INFO.
        # propagate=False — записи не дублируются в app.log/console.
        "apps.core.iis_path_debug": {
            "handlers": ["iis_path_debug_file"],
            "level": os.environ.get("LOCAL_BUSINESS_IIS_PATH_DEBUG_LOG_LEVEL", "WARNING").strip().upper(),
            "propagate": False,
        },
    },
}

LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED = env_bool("LOCAL_BUSINESS_PERFORMANCE_METRICS_ENABLED", False)
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


def database_config_from_url(database_url):
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured("DATABASE_URL must use postgres:// or postgresql://")

    query = parse_qs(parsed.query)
    options = {}
    sslmode = query.get("sslmode", [""])[0]
    if sslmode:
        options["sslmode"] = sslmode

    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "CONN_MAX_AGE": int(os.environ.get("LOCAL_BUSINESS_DB_CONN_MAX_AGE", "60")),
    }
    if options:
        config["OPTIONS"] = options
    return config


LOCAL_BUSINESS_DB_BACKEND = os.environ.get(
    "LOCAL_BUSINESS_DB_BACKEND",
    "sqlite" if DJANGO_ENV == "development" else "postgresql",
).strip().lower()
if LOCAL_BUSINESS_DB_BACKEND == "postgres":
    LOCAL_BUSINESS_DB_BACKEND = "postgresql"
if LOCAL_BUSINESS_DB_BACKEND not in {"postgresql", "sqlite"}:
    raise ImproperlyConfigured("LOCAL_BUSINESS_DB_BACKEND must be one of: postgresql, sqlite")

if DJANGO_ENV == "production" and LOCAL_BUSINESS_DB_BACKEND == "sqlite" and not env_bool(
    "LOCAL_BUSINESS_ALLOW_SQLITE_PRODUCTION",
    False,
):
    raise ImproperlyConfigured(
        "SQLite is not allowed in production for the main repository. "
        "Set LOCAL_BUSINESS_DB_BACKEND=postgresql or explicitly set "
        "LOCAL_BUSINESS_ALLOW_SQLITE_PRODUCTION=true for an emergency-only override."
    )

if LOCAL_BUSINESS_DB_BACKEND == "postgresql":
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        default_database = database_config_from_url(database_url)
    else:
        default_database = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", os.environ.get("LOCAL_BUSINESS_POSTGRES_DB", "local_business_suite")),
            "USER": os.environ.get("POSTGRES_USER", os.environ.get("LOCAL_BUSINESS_POSTGRES_USER", "local_business_app")),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", os.environ.get("LOCAL_BUSINESS_POSTGRES_PASSWORD", "")),
            "HOST": os.environ.get("POSTGRES_HOST", os.environ.get("LOCAL_BUSINESS_POSTGRES_HOST", "127.0.0.1")),
            "PORT": os.environ.get("POSTGRES_PORT", os.environ.get("LOCAL_BUSINESS_POSTGRES_PORT", "5432")),
            "CONN_MAX_AGE": int(os.environ.get("LOCAL_BUSINESS_DB_CONN_MAX_AGE", "60")),
        }
        sslmode = os.environ.get("LOCAL_BUSINESS_POSTGRES_SSLMODE", "").strip()
        if sslmode:
            default_database["OPTIONS"] = {"sslmode": sslmode}
else:
    default_database = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": Path(os.environ.get("LOCAL_BUSINESS_SQLITE_PATH", DATA_DIR / "db" / "local_business.sqlite3")),
        "OPTIONS": {
            "timeout": int(os.environ.get("LOCAL_BUSINESS_SQLITE_TIMEOUT_SECONDS", "20")),
        },
    }

DATABASES = {"default": default_database}
# DATABASE_ROUTERS не задаётся: проект работает с единственной базой ``default``
# (ADR-0029). Пути к архивным SQLite-файлам эпохи раздельных баз нужны только
# инструментам миграции и живут в apps.core.postgresql_migration, а не здесь.


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

def get_contract_path(filename, env_var, sub_dir=None):
    """Возвращает путь к рабочей копии контракта БЕЗ побочных эффектов.

    Только вычисляет путь: переопределение через переменную окружения (семантика
    env-override не меняется) либо рабочая копия в ``data/contracts/``. Импорт
    настроек больше не создаёт каталоги и не копирует дефолты — это делает
    идемпотентная команда ``python manage.py bootstrap_runtime`` (каталоги +
    копии default->runtime для контрактов, которых ещё нет в рабочей копии).

    Возвращается ВСЕГДА путь рабочей копии (или явного env-override), а не
    дефолта, — чтобы запись через Settings Center
    (``apps.settings_center.contract_services``) шла строго в ``data/contracts/``
    и не затрагивала read-only дефолты из git. Отказоустойчивость чтения при
    отсутствии рабочей копии обеспечивается отдельно: для
    role_rules/workflow_rules/workorder_status_colors — через
    ``apps.core.contract_store``, для payload-констант ниже — через
    ``_load_contract_payload`` с откатом на упакованный дефолт.
    """
    runtime_path = RUNTIME_CONTRACTS_DIR / (sub_dir or "") / filename
    override = os.environ.get(env_var, "").strip()
    return Path(override) if override else runtime_path


def _contract_default_path(runtime_path):
    """Путь упакованного дефолта для рабочего пути контракта.

    Рабочий путь и дефолт отличаются только корнем (``RUNTIME_CONTRACTS_DIR`` vs
    ``DEFAULT_CONTRACTS_DIR``), относительная часть общая. Если путь переопределён
    переменной окружения и не лежит под ``RUNTIME_CONTRACTS_DIR``, упакованного
    дефолта нет — тогда откат при чтении невозможен и используется только сам путь.
    """
    runtime_path = Path(runtime_path)
    try:
        relative = runtime_path.relative_to(RUNTIME_CONTRACTS_DIR)
    except ValueError:
        return None
    return DEFAULT_CONTRACTS_DIR / relative


def _load_contract_payload(path):
    """Грузит payload контракта для settings-констант БЕЗ побочек и БЕЗ падения импорта.

    Читает рабочую копию; при её отсутствии/ошибке — упакованный дефолт; при
    полном провале возвращает ``None`` (импорт настроек не должен падать в среде
    без выполненного ``bootstrap_runtime``). ВАЛИДАЦИЯ здесь НЕ выполняется — она
    перенесена в Django system check ``apps.core.checks`` (тег ``contracts``,
    который читает именно рабочие копии и падает на битом контракте).
    """
    path = Path(path)
    for candidate in (path, _contract_default_path(path)):
        if candidate is None:
            continue
        try:
            return load_json_file(candidate)
        except (OSError, ValueError):
            continue
    return None

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
_default_external_connector_queue_backend = "database" if LOCAL_BUSINESS_DB_BACKEND == "postgresql" else "sqlite"
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND = os.environ.get(
    "LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND",
    _default_external_connector_queue_backend,
).strip().lower()
if LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND not in {"sqlite", "database"}:
    raise ImproperlyConfigured("LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND must be one of: sqlite, database")
LOCAL_BUSINESS_ALLOW_SQLITE_AUXILIARY_PRODUCTION = env_bool("LOCAL_BUSINESS_ALLOW_SQLITE_AUXILIARY_PRODUCTION", False)
if (
    DJANGO_ENV == "production"
    and LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND == "sqlite"
    and not LOCAL_BUSINESS_ALLOW_SQLITE_AUXILIARY_PRODUCTION
):
    raise ImproperlyConfigured(
        "SQLite external connector queue is not allowed in production. "
        "Use LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND=database or set "
        "LOCAL_BUSINESS_ALLOW_SQLITE_AUXILIARY_PRODUCTION=true for an explicit emergency override."
    )
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH = Path(
    os.environ.get(
        "LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH",
        DATA_DIR / "memory" / "queues" / "external_connectors.sqlite3",
    )
)
LOCAL_BUSINESS_KNOWLEDGE_REPO_DIR = Path(
    os.environ.get("LOCAL_BUSINESS_KNOWLEDGE_REPO_DIR", DATA_DIR / "knowledge_repo")
)
LOCAL_BUSINESS_KNOWLEDGE_WRITER_QUEUE_PATH = Path(
    os.environ.get("LOCAL_BUSINESS_KNOWLEDGE_WRITER_QUEUE_PATH", DATA_DIR / "queues" / "knowledge_writer.sqlite3")
)
LOCAL_BUSINESS_SEARCH_INDEX_PATH = Path(
    os.environ.get("LOCAL_BUSINESS_SEARCH_INDEX_PATH", DATA_DIR / "indexes" / "fulltext" / "search.sqlite3")
)
_default_memory_fulltext_backend = "postgresql" if LOCAL_BUSINESS_DB_BACKEND == "postgresql" else "sqlite_fts"
LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND = os.environ.get(
    "LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND",
    _default_memory_fulltext_backend,
).strip().lower()
if LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND in {"sqlite", "fts5"}:
    LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND = "sqlite_fts"
if LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND in {"postgres", "database"}:
    LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND = "postgresql"
if LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND not in {"sqlite_fts", "postgresql"}:
    raise ImproperlyConfigured("LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND must be one of: sqlite_fts, postgresql")
if (
    DJANGO_ENV == "production"
    and LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND == "sqlite_fts"
    and not LOCAL_BUSINESS_ALLOW_SQLITE_AUXILIARY_PRODUCTION
):
    raise ImproperlyConfigured(
        "SQLite FTS search index is not allowed in production. "
        "Use LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND=postgresql or set "
        "LOCAL_BUSINESS_ALLOW_SQLITE_AUXILIARY_PRODUCTION=true for an explicit emergency override."
    )
# ADR-0030 P01: when True the knowledge file frontmatter is the authoritative
# source of metadata and a file/projection hash mismatch is a reconcile signal
# (page marked needs-reconcile) rather than a read error. Default False keeps
# the previous projection-authoritative behavior for the migration/rollback
# window; the authority is switched only after a clean memory_verify_knowledge_files.
LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE = env_bool(
    "LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE", False
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
# Единый источник правды для httpx read-timeout стримингового чата
# (``runtime_client.chat_stream`` / ``ag_ui_stream``). Чат теперь всегда
# идёт через стриминг, поэтому gunicorn-воркер удерживается до этого
# таймаута, и floor GUNICORN_TIMEOUT считается именно от него, а не от
# синхронного LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT.
LOCAL_BUSINESS_AI_STREAM_READ_TIMEOUT = float(
    os.environ.get("LOCAL_BUSINESS_AI_STREAM_READ_TIMEOUT", "600")
)
LOCAL_BUSINESS_COPILOTKIT_ENABLED = env_bool("LOCAL_BUSINESS_COPILOTKIT_ENABLED", False)
_LOCAL_BUSINESS_AI_UI_DRIVER_ENV = os.environ.get("LOCAL_BUSINESS_AI_UI_DRIVER", "").strip().lower()
LOCAL_BUSINESS_AI_UI_DRIVER_EXPLICIT = bool(_LOCAL_BUSINESS_AI_UI_DRIVER_ENV)
LOCAL_BUSINESS_AI_UI_DRIVER = _LOCAL_BUSINESS_AI_UI_DRIVER_ENV
if not LOCAL_BUSINESS_AI_UI_DRIVER and LOCAL_BUSINESS_COPILOTKIT_ENABLED:
    LOCAL_BUSINESS_AI_UI_DRIVER = "copilotkit"
if not LOCAL_BUSINESS_AI_UI_DRIVER:
    LOCAL_BUSINESS_AI_UI_DRIVER = "native"


def _validate_ai_ui_driver(value: str) -> None:
    """Проверяет допустимость ``LOCAL_BUSINESS_AI_UI_DRIVER``.

    Драйвер ``legacy`` выведен из проекта (ADR-0032): тройная матрица
    драйверов (legacy/copilotkit/native) утраивала поверхность сопровождения
    (шаблоны, статика, тесты) ради страховки, которая ни разу не понадобилась
    после того, как ``native`` стал режимом по умолчанию. Явное значение
    ``legacy`` в окружении сегодня почти всегда — забытый env со времен
    старой конфигурации (см. инцидент 2026-06-15), поэтому вместо тихого
    fallback конфигурация должна упасть сразу и понятно, а не оставить
    приложение в неожиданном состоянии.
    """
    if value == "legacy":
        raise ImproperlyConfigured(
            "LOCAL_BUSINESS_AI_UI_DRIVER=legacy больше не поддерживается: драйвер "
            "legacy выведен из проекта (ADR-0032). Уберите эту настройку из .env "
            "или замените её на LOCAL_BUSINESS_AI_UI_DRIVER=native (режим по "
            "умолчанию) либо =copilotkit."
        )
    if value not in {"copilotkit", "native"}:
        raise ImproperlyConfigured(
            "LOCAL_BUSINESS_AI_UI_DRIVER must be one of: copilotkit, native"
        )


_validate_ai_ui_driver(LOCAL_BUSINESS_AI_UI_DRIVER)
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
SETTINGS_CENTER_ENABLED = env_bool("SETTINGS_CENTER_ENABLED", True)
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
SETTINGS_CENTER_HELP_AI_ENABLED = env_bool("SETTINGS_CENTER_HELP_AI_ENABLED", True)
SETTINGS_CENTER_HELP_MODEL_PROFILE = os.environ.get(
    "SETTINGS_CENTER_HELP_MODEL_PROFILE", "local_admin_help_v1"
)
SETTINGS_CENTER_HELP_MAX_CONTEXT_CHARS = int(
    os.environ.get("SETTINGS_CENTER_HELP_MAX_CONTEXT_CHARS", "6000")
)
SETTINGS_CENTER_AUDIT_RETENTION_DAYS = int(
    os.environ.get("SETTINGS_CENTER_AUDIT_RETENTION_DAYS", "365")
)
ACCOUNTS_AD_LINK_ENABLED = env_bool("ACCOUNTS_AD_LINK_ENABLED", True)
ACCOUNTS_AD_LINK_MODE = os.environ.get("ACCOUNTS_AD_LINK_MODE", "manual").strip().lower()
ACCOUNTS_AD_GROUP_ROLE_SYNC = env_bool("ACCOUNTS_AD_GROUP_ROLE_SYNC", False)
MEMORY_ACL_INHERITANCE_ENABLED = env_bool("MEMORY_ACL_INHERITANCE_ENABLED", True)
MEMORY_ACL_FAIL_CLOSED = env_bool("MEMORY_ACL_FAIL_CLOSED", True)
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
    min_stream_timeout = int(LOCAL_BUSINESS_AI_STREAM_READ_TIMEOUT) + 30
    if GUNICORN_TIMEOUT < min_stream_timeout:
        raise ImproperlyConfigured(
            "GUNICORN_TIMEOUT must be at least LOCAL_BUSINESS_AI_STREAM_READ_TIMEOUT + 30 seconds "
            "for AI streaming requests (chat is streaming-only; a worker is held up to the "
            "stream read timeout). "
            f"Current GUNICORN_TIMEOUT={GUNICORN_TIMEOUT}, required>={min_stream_timeout}."
        )

# Payload-константы контрактов для рантайм-читателей (apps.ai / apps.memory /
# apps.filehub / apps.core.forms / apps.analytics и т.д., многие через
# ``getattr(settings, "...", default)``). Раньше здесь же выполнялась ВАЛИДАЦИЯ
# всех контрактов на импорте — она перенесена в Django system check
# ``apps.core.checks`` (тег ``contracts``), который выполняют и обычный
# ``manage.py check`` (его зовёт ``make check``), и ``check --tag contracts``, и
# system-check-фаза перед ``migrate`` в ``docker/entrypoint.prod.sh``.
#
# Здесь остаётся только ЧТЕНИЕ без побочек и без падения импорта: отсутствующая
# рабочая копия молча откатывается на упакованный дефолт (см.
# ``_load_contract_payload``), поэтому dev-запуск без ``bootstrap_runtime`` не
# падает на импорте настроек, а битый контракт по-прежнему ловит system check.
LOCAL_BUSINESS_WORKFLOW_RULES = _load_contract_payload(LOCAL_BUSINESS_WORKFLOW_RULES_FILE)
LOCAL_BUSINESS_ROLE_RULES = _load_contract_payload(LOCAL_BUSINESS_ROLE_RULES_FILE)
LOCAL_BUSINESS_WORKORDER_STATUS_COLORS = _load_contract_payload(LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE)
LOCAL_BUSINESS_INTEGRATION_REGISTRY = _load_contract_payload(LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE)
LOCAL_BUSINESS_ANALYTICS_DATASETS = _load_contract_payload(LOCAL_BUSINESS_ANALYTICS_DATASETS_FILE)
LOCAL_BUSINESS_ANALYTICS_SOURCES = _load_contract_payload(LOCAL_BUSINESS_ANALYTICS_SOURCES_FILE)
LOCAL_BUSINESS_ANALYTICS_SCOPE_RULES = _load_contract_payload(LOCAL_BUSINESS_ANALYTICS_SCOPE_RULES_FILE)
LOCAL_BUSINESS_ANALYTICS_BUSINESS_FACTS = _load_contract_payload(LOCAL_BUSINESS_ANALYTICS_BUSINESS_FACTS_FILE)
LOCAL_BUSINESS_ANALYTICS_METRICS = _load_contract_payload(LOCAL_BUSINESS_ANALYTICS_METRICS_FILE)
LOCAL_BUSINESS_ANALYTICS_MONITORS = _load_contract_payload(LOCAL_BUSINESS_ANALYTICS_MONITORS_FILE)
LOCAL_BUSINESS_ANALYTICS_DIAGNOSTIC_PLAYBOOKS = _load_contract_payload(LOCAL_BUSINESS_ANALYTICS_DIAGNOSTIC_PLAYBOOKS_FILE)
LOCAL_BUSINESS_ANALYTICS_WORKFLOW_ROUTES = _load_contract_payload(LOCAL_BUSINESS_ANALYTICS_WORKFLOW_ROUTES_FILE)
LOCAL_BUSINESS_ANALYTICS_DEDUP_RULES = _load_contract_payload(LOCAL_BUSINESS_ANALYTICS_DEDUP_RULES_FILE)
LOCAL_BUSINESS_ANALYTICS_RETENTION_PROFILES = _load_contract_payload(LOCAL_BUSINESS_ANALYTICS_RETENTION_PROFILES_FILE)
LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE = _load_contract_payload(LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE_FILE)
LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE = _load_contract_payload(LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE_FILE)
LOCAL_BUSINESS_AI_REGISTRY = _load_contract_payload(LOCAL_BUSINESS_AI_REGISTRY_FILE)
LOCAL_BUSINESS_AI_TOOLS = _load_contract_payload(LOCAL_BUSINESS_AI_TOOLS_FILE)
LOCAL_BUSINESS_AI_TASK_TYPES = _load_contract_payload(LOCAL_BUSINESS_AI_TASK_TYPES_FILE)
LOCAL_BUSINESS_AI_MODELS = _load_contract_payload(LOCAL_BUSINESS_AI_MODELS_FILE)
LOCAL_BUSINESS_AI_CHAT_SETTINGS = _load_contract_payload(LOCAL_BUSINESS_AI_CHAT_SETTINGS_FILE)
LOCAL_BUSINESS_MEMORY_PROFILES = _load_contract_payload(LOCAL_BUSINESS_MEMORY_PROFILES_FILE)
LOCAL_BUSINESS_MEMORY_ROUTING = _load_contract_payload(LOCAL_BUSINESS_MEMORY_ROUTING_FILE)
LOCAL_BUSINESS_MEMORY_TRUST_POLICY = _load_contract_payload(LOCAL_BUSINESS_MEMORY_TRUST_POLICY_FILE)
LOCAL_BUSINESS_MEMORY_CLAIMS_POLICY = _load_contract_payload(LOCAL_BUSINESS_MEMORY_CLAIMS_POLICY_FILE)
LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET = _load_contract_payload(LOCAL_BUSINESS_MEMORY_RETRIEVAL_BUDGET_FILE)
LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES = _load_contract_payload(LOCAL_BUSINESS_MEMORY_INGESTION_PROFILES_FILE)
LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES = _load_contract_payload(LOCAL_BUSINESS_MEMORY_FILE_ORGANIZATION_PROFILES_FILE)
LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA = _load_contract_payload(LOCAL_BUSINESS_MEMORY_GRAPH_SCHEMA_FILE)
LOCAL_BUSINESS_MEMORY_SOURCES = _load_contract_payload(LOCAL_BUSINESS_MEMORY_SOURCES_FILE)
