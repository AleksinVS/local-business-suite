import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]

load_dotenv(BASE_DIR / ".env")


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
    ai_task_types_path: Path
    ai_models_path: Path
    system_prompt_path: Path | None


def load_runtime_settings() -> RuntimeSettings:
    model_name = os.environ.get("AI_AGENT_MODEL_NAME")
    if model_name:
        default_model = f"openai:{model_name}"
    else:
        default_model = "openai:gpt-4.1-mini"
    return RuntimeSettings(
        model=os.environ.get("AI_AGENT_MODEL", default_model),
        django_gateway_url=os.environ.get(
            "DJANGO_AI_GATEWAY_URL", "http://127.0.0.1:8000/ai/gateway"
        ).rstrip("/"),
        django_gateway_token=os.environ.get(
            "LOCAL_BUSINESS_AI_GATEWAY_TOKEN", "dev-ai-gateway-token"
        ),
        ai_tools_path=Path(
            os.environ.get(
                "LOCAL_BUSINESS_AI_TOOLS_FILE",
                BASE_DIR / "config" / "ai" / "tools.json",
            )
        ),
        ai_task_types_path=Path(
            os.environ.get(
                "LOCAL_BUSINESS_AI_TASK_TYPES_FILE",
                BASE_DIR / "config" / "ai" / "task_types.json",
            )
        ),
        ai_models_path=Path(
            os.environ.get(
                "LOCAL_BUSINESS_AI_MODELS_FILE",
                BASE_DIR / "config" / "ai" / "models.json",
            )
        ),
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


def load_models_config() -> list[ModelConfig]:
    settings = load_runtime_settings()
    path = settings.ai_models_path
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
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
    return json.loads(path.read_text(encoding="utf-8"))
