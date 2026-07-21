import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from . import contract_cache

BASE_DIR = Path(__file__).resolve().parents[2]

load_dotenv(BASE_DIR / ".env")

DEFAULT_CONTRACTS_DIR = BASE_DIR / "contracts"
RUNTIME_CONTRACTS_DIR = BASE_DIR / "data" / "contracts"

# Source labels for _resolve_contract()/RuntimeSettings.*_source.
CONTRACT_SOURCE_OVERRIDE = "override"
CONTRACT_SOURCE_RUNTIME = "runtime"
CONTRACT_SOURCE_DEFAULT = "default"


def _resolve_contract(filename: str, env_var: str, sub_dir: str = "ai") -> tuple[Path, str]:
    """Resolve a contract file path and report which source provided it.

    Re-run on every call (never memoized): the caller is expected to call
    this fresh each time it needs a path, so a Settings Center runtime
    copy created after this process started (ADR-0031 п.3, first-start
    race with Django) is picked up on the very next call instead of being
    stuck on whatever was true at process start.
    """
    override = os.environ.get(env_var, "").strip()
    if override:
        return Path(override), CONTRACT_SOURCE_OVERRIDE
    runtime_path = RUNTIME_CONTRACTS_DIR / sub_dir / filename
    if runtime_path.exists():
        return runtime_path, CONTRACT_SOURCE_RUNTIME
    return DEFAULT_CONTRACTS_DIR / sub_dir / filename, CONTRACT_SOURCE_DEFAULT


def _contract_path(filename: str, env_var: str, sub_dir: str = "ai") -> Path:
    path, _source = _resolve_contract(filename, env_var, sub_dir)
    return path


@dataclass(frozen=True)
class ModelConfig:
    id: str
    name: str
    model: str
    provider: str = ""
    base_url: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    is_default: bool = False


@dataclass(frozen=True)
class ResolvedModel:
    model: str
    provider: str
    base_url: str
    api_key: str


@dataclass(frozen=True)
class RuntimeSettings:
    model: str
    django_gateway_url: str
    django_gateway_token: str
    ai_tools_path: Path
    ai_tools_source: str
    ai_task_types_path: Path
    ai_task_types_source: str
    ai_models_path: Path
    ai_models_source: str
    system_prompt_path: Path | None


def load_runtime_settings() -> RuntimeSettings:
    model_name = os.environ.get("AI_AGENT_MODEL_NAME")
    if model_name:
        default_model = f"openai:{model_name}"
    else:
        default_model = "openai:gpt-4.1-mini"
    ai_tools_path, ai_tools_source = _resolve_contract(
        "tools.json", "LOCAL_BUSINESS_AI_TOOLS_FILE"
    )
    ai_task_types_path, ai_task_types_source = _resolve_contract(
        "task_types.json", "LOCAL_BUSINESS_AI_TASK_TYPES_FILE"
    )
    ai_models_path, ai_models_source = _resolve_contract(
        "models.json", "LOCAL_BUSINESS_AI_MODELS_FILE"
    )
    return RuntimeSettings(
        model=os.environ.get("AI_AGENT_MODEL", default_model),
        django_gateway_url=os.environ.get(
            "DJANGO_AI_GATEWAY_URL", "http://127.0.0.1:8000/ai/gateway"
        ).rstrip("/"),
        django_gateway_token=os.environ.get(
            "LOCAL_BUSINESS_AI_GATEWAY_TOKEN", "dev-ai-gateway-token"
        ),
        ai_tools_path=ai_tools_path,
        ai_tools_source=ai_tools_source,
        ai_task_types_path=ai_task_types_path,
        ai_task_types_source=ai_task_types_source,
        ai_models_path=ai_models_path,
        ai_models_source=ai_models_source,
        system_prompt_path=Path(
            os.environ.get(
                "AI_AGENT_SYSTEM_PROMPT_FILE",
                BASE_DIR
                / "services"
                / "agent_runtime"
                / "prompts"
                / "hospital_system_prompt.txt",
            )
        ),
    )


def describe_contract_sources() -> list[dict]:
    """Diagnostic snapshot of where each AI contract file is actually being
    read from right now (recomputed fresh, nothing cached here).

    Used for the agent-runtime startup log (ADR-0031 п.3 шаг 1): a
    ``source`` of ``"default"`` means the Settings Center runtime copy
    under ``data/contracts/ai/`` was not visible to this process — most
    commonly because ``./data`` is not mounted into the container, or
    because Django has not created the runtime copy yet.
    """
    settings = load_runtime_settings()
    return [
        {
            "name": "ai_tools",
            "path": str(settings.ai_tools_path),
            "source": settings.ai_tools_source,
        },
        {
            "name": "ai_task_types",
            "path": str(settings.ai_task_types_path),
            "source": settings.ai_task_types_source,
        },
        {
            "name": "ai_models",
            "path": str(settings.ai_models_path),
            "source": settings.ai_models_source,
        },
    ]


def load_models_config() -> list[ModelConfig]:
    settings = load_runtime_settings()
    path = settings.ai_models_path
    if not path.exists():
        return []
    raw = load_json(path)
    return [
        ModelConfig(
            id=cfg["id"],
            name=cfg["name"],
            model=cfg["model"],
            provider=cfg.get("provider", ""),
            base_url=cfg.get("base_url", ""),
            api_key_env=cfg.get("api_key_env", "OPENAI_API_KEY"),
            is_default=cfg.get("default", False),
        )
        for cfg in raw
    ]


def resolve_model(model_id: str = "") -> ResolvedModel:
    settings = load_runtime_settings()
    models = load_models_config()

    if model_id:
        for m in models:
            if m.id == model_id:
                api_key = os.environ.get(m.api_key_env, "")
                return ResolvedModel(
                    model=m.model,
                    provider=m.provider,
                    base_url=m.base_url or os.environ.get("OPENAI_BASE_URL", ""),
                    api_key=api_key,
                )

    # Fallback: use default from config or settings
    default_model = next((m for m in models if m.is_default), None)
    if default_model:
        api_key = os.environ.get(default_model.api_key_env, "")
        return ResolvedModel(
            model=default_model.model,
            provider=default_model.provider,
            base_url=default_model.base_url or os.environ.get("OPENAI_BASE_URL", ""),
            api_key=api_key,
        )

    # Ultimate fallback: use the environment default
    return ResolvedModel(
        model=settings.model,
        provider="",
        base_url=os.environ.get("OPENAI_BASE_URL", ""),
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    )


def get_available_models() -> list[dict]:
    """Return model list safe for API exposure (no secrets)."""
    models = load_models_config()
    return [
        {"id": m.id, "name": m.name, "default": m.is_default}
        for m in models
    ]


def load_json(path: Path):
    """Load and parse a contract JSON file, cached by the file's
    ``(st_mtime_ns, st_size, st_ino)`` key (see ``contract_cache``).

    ``path`` should come from a fresh call to ``_contract_path``/
    ``_resolve_contract`` (e.g. via ``load_runtime_settings()``) so a
    runtime copy that appears or changes after this process started is
    picked up without a restart.
    """
    return contract_cache.load_json_cached(path)
