import json
import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RuntimeSettings:
    model: str
    django_gateway_url: str
    django_gateway_token: str
    ai_tools_path: Path
    ai_task_types_path: Path
    system_prompt_path: Path | None


def load_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings(
        model=os.environ.get("AI_AGENT_MODEL", "openai:gpt-4.1-mini"),
        django_gateway_url=os.environ.get("DJANGO_AI_GATEWAY_URL", "http://web:8000/ai/gateway").rstrip("/"),
        django_gateway_token=os.environ.get("LOCAL_BUSINESS_AI_GATEWAY_TOKEN", "dev-ai-gateway-token"),
        ai_tools_path=Path(os.environ.get("LOCAL_BUSINESS_AI_TOOLS_FILE", BASE_DIR / "config" / "ai" / "tools.json")),
        ai_task_types_path=Path(
            os.environ.get("LOCAL_BUSINESS_AI_TASK_TYPES_FILE", BASE_DIR / "config" / "ai" / "task_types.json")
        ),
        system_prompt_path=Path(os.environ["AI_AGENT_SYSTEM_PROMPT_FILE"])
        if os.environ.get("AI_AGENT_SYSTEM_PROMPT_FILE")
        else None,
    )


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
