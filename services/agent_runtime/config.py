import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from . import contract_cache

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
    system_prompt_path: Path | None


class RuntimePolicyError(RuntimeError):
    """The delivered tool/task policy cannot authorize a runtime operation."""


def _snapshot_payload(snapshot, document_id):
    if not isinstance(snapshot, dict) or document_id not in snapshot:
        raise RuntimePolicyError(f"AI policy snapshot is missing {document_id}.")
    value = snapshot[document_id]
    payload = value.get("payload", value) if isinstance(value, dict) else getattr(value, "payload", value)
    if not isinstance(payload, (dict, list)):
        raise RuntimePolicyError(f"AI policy payload {document_id} is invalid.")
    return payload


def _delivered_tool_catalog(snapshot):
    """Return the static registry and a validated delivered catalog.

    The Python registry is the security ceiling.  A gateway snapshot may only
    narrow it; it may never add tools or change their execution mode or
    confirmation requirement.
    """
    from apps.ai.tool_definitions import get_tool_registry

    static_registry = get_tool_registry()
    payload = _snapshot_payload(snapshot, "ai.contract.tools")
    delivered_tools = payload.get("tools") if isinstance(payload, dict) else None
    if not isinstance(delivered_tools, list):
        raise RuntimePolicyError("Delivered AI tool policy is missing.")
    delivered_by_id = {}
    for item in delivered_tools:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise RuntimePolicyError("Delivered AI tool policy contains an invalid tool.")
        if item["id"] in delivered_by_id:
            raise RuntimePolicyError("Delivered AI tool policy contains duplicate tools.")
        delivered_by_id[item["id"]] = item
    if not set(delivered_by_id).issubset(static_registry):
        raise RuntimePolicyError("Delivered AI tools differ from the static registry.")
    for tool_id, delivered_tool in delivered_by_id.items():
        static_tool = static_registry[tool_id]
        if delivered_tool.get("mode") != static_tool.get("mode"):
            raise RuntimePolicyError(f"AI tool mode drift for {tool_id}.")
        if bool(delivered_tool.get("requires_confirmation", False)) != bool(
            static_tool.get("requires_confirmation", False)
        ):
            raise RuntimePolicyError(f"AI tool confirmation drift for {tool_id}.")
    return static_registry, delivered_by_id


def _validated_tasks(snapshot, static_registry):
    payload = _snapshot_payload(snapshot, "ai.contract.task_types")
    tasks = payload.get("task_types") if isinstance(payload, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise RuntimePolicyError("Delivered AI task policy is missing.")
    seen_ids = set()
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task["id"]:
            raise RuntimePolicyError("Delivered AI task policy contains an invalid task.")
        if task["id"] in seen_ids:
            raise RuntimePolicyError("Delivered AI task policy contains duplicate tasks.")
        seen_ids.add(task["id"])
        allowed_tools = task.get("allowed_tools")
        if not isinstance(allowed_tools, list) or any(
            not isinstance(tool_id, str) or tool_id not in static_registry
            for tool_id in allowed_tools
        ):
            raise RuntimePolicyError(f"Task policy {task['id']} has invalid allowed_tools.")
        if type(task.get("requires_confirmation")) is not bool:
            raise RuntimePolicyError(f"Task policy {task['id']} has invalid confirmation policy.")
        if not isinstance(task.get("mode"), str) or task.get("mode") not in {"read", "write"}:
            raise RuntimePolicyError(f"Task policy {task['id']} has invalid mode.")
    return tasks


def _task_candidates(tool_code, static_tool, tasks):
    exact = [
        task for task in tasks
        if task["id"] == tool_code and tool_code in task["allowed_tools"]
    ]
    if exact:
        candidates = exact
    else:
        # Helper tools may appear in a write task and in a standalone lookup
        # task.  Only the task whose mode matches the static tool mode can
        # authorize this operation.
        candidates = [
            task for task in tasks
            if tool_code in task["allowed_tools"]
            and task["mode"] == static_tool.get("mode")
        ]
    return candidates


def _effective_policy(tool_code, static_tool, tasks):
    candidates = _task_candidates(tool_code, static_tool, tasks)
    if not candidates:
        raise RuntimePolicyError(f"Tool {tool_code} is outside delivered task policy.")
    if any(task["mode"] != static_tool.get("mode") for task in candidates):
        raise RuntimePolicyError(f"Task mode drift for {tool_code}.")
    confirmations = {task["requires_confirmation"] for task in candidates}
    if len(confirmations) != 1:
        raise RuntimePolicyError(f"Task confirmation policy conflicts for {tool_code}.")
    static_confirmation = bool(static_tool.get("requires_confirmation", False))
    if next(iter(confirmations)) != static_confirmation:
        raise RuntimePolicyError(f"Task confirmation drift for {tool_code}.")
    task = sorted(candidates, key=lambda item: item["id"])[0]
    return {
        "tool_code": tool_code,
        "mode": static_tool.get("mode"),
        "requires_confirmation": static_confirmation,
        "task_type_id": task["id"],
        "task_type_title": task.get("title", ""),
        "task_type_mode": task["mode"],
        "required_slots": list(task.get("required_slots") or []),
    }


def resolve_effective_tool_policy(tool_code: str, *, snapshot=None):
    """Resolve one executable tool before any model/tool invocation."""
    snapshot = load_ai_contract_snapshot() if snapshot is None else snapshot
    static_registry, delivered = _delivered_tool_catalog(snapshot)
    static_tool = static_registry.get(tool_code)
    if static_tool is None:
        raise RuntimePolicyError("Tool is not in the static runtime registry.")
    if tool_code not in delivered:
        raise RuntimePolicyError("Tool is not in the delivered runtime policy.")
    tasks = _validated_tasks(snapshot, static_registry)
    return _effective_policy(tool_code, static_tool, tasks)


def get_effective_tool_policies(*, snapshot=None):
    """Return only tools in the static∩delivered∩task-policy intersection."""
    snapshot = load_ai_contract_snapshot() if snapshot is None else snapshot
    static_registry, _delivered = _delivered_tool_catalog(snapshot)
    tasks = _validated_tasks(snapshot, static_registry)
    policies = {}
    for tool_code, static_tool in static_registry.items():
        if tool_code not in _delivered:
            continue
        if not any(tool_code in task["allowed_tools"] for task in tasks):
            continue
        policies[tool_code] = _effective_policy(tool_code, static_tool, tasks)
    return policies


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


def load_models_config(*, snapshot=None) -> list[ModelConfig]:
    raw = load_delivered_json("ai.contract.models", snapshot=snapshot)
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


def resolve_model(model_id: str = "", *, snapshot=None) -> ResolvedModel:
    settings = load_runtime_settings()
    snapshot = load_ai_contract_snapshot() if snapshot is None else snapshot
    models = load_models_config(snapshot=snapshot)

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


def is_model_configured(model_id: str = "", *, snapshot=None) -> bool:
    """Проверяет наличие выбранной модели и требуемого ею ключа провайдера."""
    # Calling the public loader here preserves its test/integration seam while
    # a graph operation passes an already-frozen snapshot explicitly.
    models = load_models_config(
        snapshot=snapshot
    ) if snapshot is not None else load_models_config()
    selected = None
    if model_id:
        selected = next((model for model in models if model.id == model_id), None)
        if selected is None:
            return False
    else:
        selected = next((model for model in models if model.is_default), None)

    if selected is not None:
        if not selected.model:
            return False
        return not selected.api_key_env or bool(os.environ.get(selected.api_key_env, ""))

    settings = load_runtime_settings()
    return bool(settings.model and os.environ.get("OPENAI_API_KEY", ""))


def get_available_models(*, snapshot=None) -> list[dict]:
    """Return model list safe for API exposure (no secrets)."""
    models = load_models_config(snapshot=snapshot)
    return [
        {"id": m.id, "name": m.name, "default": m.is_default}
        for m in models
    ]


def load_ai_contract_snapshot():
    """Fetch one complete, validated AI aggregate for one runtime operation."""
    settings = load_runtime_settings()
    return contract_cache.load_gateway_snapshot(
        gateway_url=settings.django_gateway_url,
        token=settings.django_gateway_token,
    )


def get_ai_contract_diagnostics(*, refresh: bool = False) -> dict:
    """Return safe delivery diagnostics without exposing payloads or paths."""
    settings = load_runtime_settings()
    cache = contract_cache.get_gateway_cache(
        gateway_url=settings.django_gateway_url,
        token=settings.django_gateway_token,
    )
    if refresh:
        try:
            cache.snapshot()
        except Exception:
            # The cache records a bounded, non-sensitive error code.  Health
            # callers must still receive diagnostics when the gateway is down.
            pass
    return cache.diagnostics()


def load_delivered_json(document_id: str, *, snapshot=None):
    """Fetch one document from the aggregate gateway snapshot.

    This explicit API is used by consumers after their individual cutover.
    """
    snapshot = load_ai_contract_snapshot() if snapshot is None else snapshot
    value = snapshot[document_id]
    return value.get("payload", value) if isinstance(value, dict) else value.payload


def _task_types_payload(snapshot):
    return load_delivered_json("ai.contract.task_types", snapshot=snapshot)


def normalize_task_value(value, *, field: str, snapshot=None):
    """Normalize a status/priority alias from the operation's task snapshot.

    The runtime deliberately does not import the legacy in-code task catalog:
    aliases are policy data and must come from the immutable aggregate passed
    to this operation. Unknown values pass through for Django validation.
    """
    if not value:
        return value
    snapshot = load_ai_contract_snapshot() if snapshot is None else snapshot
    aliases_by_key = {}
    for task in _task_types_payload(snapshot).get("task_types", []):
        for canonical, aliases in (task.get(field) or {}).items():
            aliases_by_key.setdefault(str(canonical), tuple(str(alias) for alias in aliases))
    if value in aliases_by_key:
        return value
    folded = str(value).casefold()
    for canonical, aliases in aliases_by_key.items():
        if any(folded == alias.casefold() for alias in aliases):
            return canonical
    return value


def normalize_status(value, *, snapshot=None):
    return normalize_task_value(value, field="status_aliases", snapshot=snapshot)


def normalize_priority(value, *, snapshot=None):
    return normalize_task_value(value, field="priority_aliases", snapshot=snapshot)


def resolve_task_type_for_snapshot(tool_id: str, slot_values=None, *, snapshot=None):
    """Resolve delivered task policy for one tool call without a legacy catalog."""
    snapshot = load_ai_contract_snapshot() if snapshot is None else snapshot
    slot_values = slot_values or {}
    payload = _task_types_payload(snapshot)
    for task in payload.get("task_types", []):
        allowed_tools = task.get("allowed_tools") or []
        if tool_id not in allowed_tools:
            continue
        required = tuple(task.get("required_slots") or ())
        missing = [
            slot for slot in required
            if slot_values.get(slot) is None or slot_values.get(slot) == ""
        ]
        return {
            "task_type_id": task.get("id", ""),
            "task_type_title": task.get("title", ""),
            "task_type_mode": task.get("mode", ""),
            "resolved_tool": tool_id,
            "requires_confirmation": bool(task.get("requires_confirmation", False)),
            "slot_state": {
                key: value for key, value in slot_values.items()
                if value is not None and value != ""
            },
            "missing_required_slots": missing,
            "all_slots_fulfilled": not missing,
        }
    return None
